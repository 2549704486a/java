package com.budou.incentive.infra;
import com.alibaba.otter.canal.client.CanalConnector;
import com.alibaba.otter.canal.client.CanalConnectors;
import com.alibaba.otter.canal.protocol.CanalEntry;
import com.alibaba.otter.canal.protocol.Message;
import com.budou.incentive.config.CanalClientProperties;
import com.budou.incentive.dao.redis.RedisDao;
import com.google.protobuf.ByteString;
import com.google.protobuf.InvalidProtocolBufferException;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.net.InetSocketAddress;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.*;

/**
 * RDSBinlog 类
 *
 * 功能：监听MySQL数据库的binlog日志，实时获取数据库变更信息并同步到Redis缓存
 *
 * 原理：使用Alibaba Canal组件连接MySQL，订阅binlog事件，当数据库表发生变更时
 * 获取变更内容，根据不同的表和操作类型进行相应处理，更新Redis缓存
 */
@Slf4j  // Lombok注解，自动创建日志对象log
@Component  // Spring注解，标记为Spring组件，会被自动扫描和注册
@ConditionalOnProperty(prefix = "canal.client", name = "enabled", havingValue = "true", matchIfMissing = true)
public class RDSBinlog {
    // 用于存储错误信息，避免重复打印相同错误
    private final Map<String, String> errorMap = new HashMap<>();

    @Autowired  // 自动注入RedisDao，用于操作Redis
    private RedisDao redisDao;

    @Autowired
    private CanalClientProperties canalClientProperties;

    /**
     * 在Bean初始化完成后自动调用
     * 启动一个单独的线程进行Canal连接和数据处理
     */
    @PostConstruct
    private void initThread() {
        Thread canalThread = new Thread(() -> {
            while (!Thread.currentThread().isInterrupted()) {
                try {
                    initConnect();  // 尝试初始化Canal连接
                } catch (Exception e) {
                    String key = "canal_connection_error";
                    if (!hasSameError(key, e.getMessage())) {
                        log.error("canal连接出错: {}", e);  // 只有当错误信息变化时才记录日志
                    }
                }
                sleepQuietly(canalClientProperties.getRetryIntervalMs());  // 连接失败后休眠再重试
            }
        }, "canal-sync-thread");
        canalThread.setDaemon(true);
        canalThread.start();  // 启动线程
    }

    /**
     * 初始化Canal连接并处理数据变更
     *
     * 连接Canal服务器，订阅所有数据库和表的变更信息
     * 持续从Canal获取数据，并调用处理方法
     */
    private void initConnect() {
        // 创建连接器，连接到Canal服务器
        CanalConnector connector = CanalConnectors.newSingleConnector(
                new InetSocketAddress(canalClientProperties.getHost(), canalClientProperties.getPort()),
                canalClientProperties.getDestination(),
                canalClientProperties.getUsername(),
                canalClientProperties.getPassword());

        int batchSize = canalClientProperties.getBatchSize();

        try {
            connector.connect();  // 连接到Canal服务器
            connector.subscribe(canalClientProperties.getSubscribePattern());  // 订阅所有数据库和表的变更信息
            connector.rollback();  // 回滚到未进行ack的位置，确保不遗漏数据
            /**
             * 情况1：没有使用rollback
             *
             * 你的Canal客户端在昨天晚上23:00连接到Canal服务器并工作
             * 处理了一批ID为1000的消息（包含100条商品价格更新）
             * 由于系统故障，客户端在处理完80条后崩溃，没有发送ack确认
             * 今天早上9:00，你重启了客户端程序
             *
             * 没有rollback的结果：Canal可能会从上次的默认位置或者新位置开始，那20条未处理的商品价格更新就永久丢失了，导致数据不一致。
             * 情况2：使用了rollback
             *
             * 同样的情况，客户端崩溃后未确认批次1000
             * 今天早上9:00重启客户端
             * 连接后立即执行connector.rollback();
             * Canal将位置重置到批次1000的开始
             *
             * 使用rollback的结果：客户端会重新获取批次1000的全部消息，虽然会重复处理前80条（需要你的处理逻辑支持幂等性），但保证了那20条未处理的记录不会丢失。
             */
            log.info("canal连接成功");  // 记录连接成功日志

            while (true) {
                // 获取指定数量的数据，不进行确认（ack）
                Message message = connector.getWithoutAck(batchSize);

                // 获取批次ID和消息数量
                long batchId = message.getId();
                int size = message.getEntries().size();
//                log.info("batchId = " + batchId + " size = " + size);

                // 判断是否获取到数据
                if (batchId == -1 || size == 0) {
                    sleepQuietly(canalClientProperties.getIdleDelayMs());  // 未获取到数据时休眠
                } else {
                    try {
                        // 有数据时进行处理
                        log.info("从canal接收到: {} 条消息,消息批次: {}，开始处理", size, message.getId());
                        handleMessage(message.getEntries());  // 处理获取到的binlog条目
                    } catch (Exception e) {
                        log.error("handleMessage exception", e);
                        connector.rollback(batchId);  // 处理失败时回滚，确保数据不丢失

                        // 错误处理逻辑，避免重复打印相同错误
                        String key = "canal_sync_data_error";
                        String errMsg = e.getMessage();
                        if (StringUtils.isEmpty(errMsg)) errMsg = e.toString();
                        if (!hasSameError(key, errMsg)) {
                            log.error("同步数据出错: {}", e);
                        }

                        // 出错后休眠10秒再继续
                        sleepQuietly(canalClientProperties.getRetryIntervalMs());
                        continue;
                    }
                }
                connector.ack(batchId);  // 处理成功后确认批次，表示已处理完成
            }
        } catch (Exception e) {
            log.error("==========error", e);
        } finally {
            connector.disconnect();  // 确保连接关闭
        }
    }

    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.warn("canal线程被中断");
        }
    }

    /**
     * 检查是否为相同错误
     *
     * 用于避免相同错误反复记录日志
     *
     * @param key 错误类型的键
     * @param error 错误信息
     * @return 是否为相同错误
     */
    private boolean hasSameError(String key, String error) {
        String lastError = errorMap.get(key);
        if (Objects.equals(lastError, error)) {
            return true;  // 如果错误信息相同，返回true
        }
        errorMap.put(key, error);  // 更新错误信息
        return false;
    }

    /**
     * 处理binlog消息
     *
     * 解析binlog条目，判断操作类型(INSERT/UPDATE/DELETE)
     * 根据表名和操作类型调用对应的处理方法
     *
     * @param entrys binlog条目列表
     * @throws InvalidProtocolBufferException Protocol Buffer解析异常
     */
    private void handleMessage(List<CanalEntry.Entry> entrys) throws InvalidProtocolBufferException {
//        System.out.println("RDSBinlog.handleMessage:正在解析binlog");
        for (CanalEntry.Entry entry : entrys) {
            // 跳过事务开始和结束的条目
            if (entry.getEntryType() == CanalEntry.EntryType.TRANSACTIONBEGIN || entry.getEntryType() == CanalEntry.EntryType.TRANSACTIONEND) {
                continue;
            }

            // 获取数据库名和表名
            String databaseName = entry.getHeader().getSchemaName();
            String tableName = entry.getHeader().getTableName();
//            log.info("数据库: {}, 表名: {}", databaseName, tableName);

            // 获取条目类型
            CanalEntry.EntryType entryType = entry.getEntryType();

            // 获取存储的二进制数据
            ByteString storeValue = entry.getStoreValue();

            // 只处理ROWDATA类型的条目（表示表的行数据变更）
            if (CanalEntry.EntryType.ROWDATA.equals(entryType)) {
                // 解析行变更数据
                CanalEntry.RowChange rowChange = CanalEntry.RowChange.parseFrom(storeValue);
                // 获取事件类型（INSERT/UPDATE/DELETE）
                CanalEntry.EventType eventType = rowChange.getEventType();

                // 获取所有行数据
                List<CanalEntry.RowData> rowDatasList = rowChange.getRowDatasList();

                // 根据事件类型调用对应的处理方法
                if(eventType == CanalEntry.EventType.UPDATE){
                    handleUpdate(tableName, rowDatasList);  // 处理更新操作
                }else if(eventType == CanalEntry.EventType.INSERT){
                    handleInsert(tableName, rowDatasList);  // 处理插入操作
                }else if(eventType == CanalEntry.EventType.DELETE){
                    handleDelete(tableName, rowDatasList);  // 处理删除操作
                }
            }
        }
    }

    /**
     * 处理DELETE操作
     *
     * 根据表名调用对应的删除处理方法
     * 注：当前代码中该方法实现被注释掉
     *
     * @param tableName 表名
     * @param rowDatasList 行数据列表
     */
    private void handleDelete(String tableName, List<CanalEntry.RowData> rowDatasList) {
        if (tableName.equals("user_award")) {
            handleDeleteUserAward(rowDatasList);
        }
    }

    /**
     * 处理INSERT操作
     *
     * 根据表名调用对应的插入处理方法
     * 注：当前未实现任何处理逻辑
     *
     * @param tableName 表名
     * @param rowDatasList 行数据列表
     */
    private void handleInsert(String tableName, List<CanalEntry.RowData> rowDatasList) {
        // 当前暂未对插入做缓存处理，必要时可在此补充
    }

    /**
     * 处理UPDATE操作
     *
     * 根据表名调用对应的更新处理方法
     *
     * @param tableName 表名
     * @param rowDatasList 行数据列表
     */
    private void handleUpdate(String tableName, List<CanalEntry.RowData> rowDatasList) {
        // 根据表名分派到不同的处理方法
        if (tableName.equals("user_award")) {
            handleUpdateUserAward(rowDatasList);  // 处理用户奖品表更新
        }
        if (tableName.equals("user_currency")) {
            handleUpdateUserCurrency(rowDatasList);  // 处理用户货币表更新
        }
        if (tableName.equals("award_config")){
            handleUpdateAwardConfig(rowDatasList);  // 处理奖品配置表更新
        }
        if (tableName.equals("award_inventory_split")){
            handleUpdateAwardInventorySplit(rowDatasList);  // 处理奖品库存分配表更新
        }
    }

    /**
     * 处理奖品库存分配表的更新
     *
     * 从行数据中获取奖品ID、库存数量等信息
     * 更新Redis中对应的缓存数据
     *
     * @param rowDatasList 行数据列表
     */
    private void handleUpdateAwardInventorySplit(List<CanalEntry.RowData> rowDatasList) {
        for(CanalEntry.RowData rowData : rowDatasList){
            // 获取更新前后的列数据，同步维护分片库存和总库存缓存
            List<CanalEntry.Column> afterColumnsList = rowData.getAfterColumnsList();
            List<CanalEntry.Column> beforeColumnsList = rowData.getBeforeColumnsList();
            String awardInventorySplitKey = "";  // Redis缓存键：奖品库存分配
            String awardConfigInventoryKey = "";
            String hashKey = "";  // Redis哈希字段
            Integer inventory = 0;  // 库存数量
            Integer beforeInventory = null;

            // 遍历所有列获取需要的数据
            for(CanalEntry.Column column : afterColumnsList){
                if(column.getName().equals("awardId")){
                    // 构建Redis缓存键
                    awardInventorySplitKey = "award_inventory_split:" + column.getValue();
                    awardConfigInventoryKey = "award_config:inventory:" + column.getValue();
                }
                if(column.getName().equals("inventory")){
                    inventory = Integer.valueOf(column.getValue());  // 获取库存数量
                }
                if(column.getName().equals("splitId")){
                    hashKey = "splitId:" +  column.getValue();  // 构建哈希字段
                }
            }

            for(CanalEntry.Column column : beforeColumnsList){
                if(column.getName().equals("inventory")){
                    beforeInventory = Integer.valueOf(column.getValue());
                }
            }

            // 根据库存数量更新Redis缓存
            if (inventory == 0) {
                // 库存为0时删除对应的哈希字段
                redisDao.hmDel(awardInventorySplitKey, hashKey);
            } else {
                // 库存不为0时设置哈希字段
                redisDao.hmSet(awardInventorySplitKey, hashKey, inventory);
            }

            syncAwardInventorySummary(awardConfigInventoryKey, awardInventorySplitKey, beforeInventory, inventory);
        }
    }

    private void syncAwardInventorySummary(String awardConfigInventoryKey,
                                           String awardInventorySplitKey,
                                           Integer beforeInventory,
                                           Integer afterInventory) {
        if (StringUtils.isBlank(awardConfigInventoryKey) || StringUtils.isBlank(awardInventorySplitKey)) {
            return;
        }

        Integer totalInventory = null;
        if (beforeInventory != null) {
            Object currentInventory = redisDao.get(awardConfigInventoryKey);
            if (currentInventory instanceof Number) {
                int delta = afterInventory - beforeInventory;
                totalInventory = ((Number) currentInventory).intValue() + delta;
            }
        }

        if (totalInventory == null) {
            totalInventory = 0;
            List<Object> splitInventories = redisDao.hmValues(awardInventorySplitKey);
            for (Object splitInventory : splitInventories) {
                if (splitInventory instanceof Number) {
                    totalInventory += ((Number) splitInventory).intValue();
                } else if (splitInventory != null) {
                    totalInventory += Integer.parseInt(splitInventory.toString());
                }
            }
        }

        redisDao.set(awardConfigInventoryKey, totalInventory);
    }

    /**
     * 处理用户货币表的更新
     *
     * 从行数据中获取用户ID、货币数量等信息
     * 更新Redis中对应的缓存数据
     *
     * @param rowDatasList 行数据列表
     */
    private void handleUpdateUserCurrency(List<CanalEntry.RowData> rowDatasList) {
        for(CanalEntry.RowData rowData : rowDatasList){
            // 获取更新后的列数据
            List<CanalEntry.Column> afterColumnsList = rowData.getAfterColumnsList();
            String userId = "";
            Integer currency = 0;

            // 遍历所有列获取需要的数据
            for(CanalEntry.Column column : afterColumnsList){
                if(column.getName().equals("userId")){
                    userId = column.getValue();  // 获取用户ID
                }
                if(column.getName().equals("currency")){
                    currency = Integer.valueOf(column.getValue());  // 获取货币数量
                }
            }

            // 构建缓存键并更新Redis
            String userCurrencyKey = "user_currency:" + userId;
            redisDao.set(userCurrencyKey, currency);
        }
    }

    /**
     * 处理用户奖品表的更新
     *
     * 从行数据中获取用户ID、奖品ID、状态等信息
     * 更新Redis中对应的缓存数据
     *
     * @param rowDatasList 行数据列表
     */
    private void handleUpdateUserAward(List<CanalEntry.RowData> rowDatasList) {
        for (CanalEntry.RowData rowData : rowDatasList) {
            // 获取更新后的列数据
            List<CanalEntry.Column> afterColumnsList = rowData.getAfterColumnsList();
            String userId = "";
            String awardId = "";
            Integer status = null;

            for (CanalEntry.Column column : afterColumnsList) {
                if (column.getName().equals("userId")) {
                    userId = column.getValue();
                }
                if (column.getName().equals("awardId")) {
                    awardId = column.getValue();
                }
                if (column.getName().equals("status")) {
                    status = Integer.valueOf(column.getValue());
                }
            }

            if (StringUtils.isBlank(userId) || StringUtils.isBlank(awardId) || status == null) {
                continue;
            }

            String userAwardStatusKey = "user_award:status:" + userId + ":" + awardId;
            redisDao.set(userAwardStatusKey, status);
        }
    }

    /**
     * 处理奖品配置表的更新
     *
     * 从行数据中获取奖品ID、库存、是否允许超卖、结束时间、价格等信息
     * 更新Redis中对应的缓存数据
     *
     * @param rowDatasList 行数据列表
     */
    private void handleUpdateAwardConfig(List<CanalEntry.RowData> rowDatasList) {
        for (CanalEntry.RowData rowData : rowDatasList) {
            // 获取更新后的列数据
            List<CanalEntry.Column> afterColumnsList = rowData.getAfterColumnsList();
            String awardId = "";

            // 首先获取奖品ID
            for (CanalEntry.Column column : afterColumnsList) {
                if (column.getName().equals("awardId")) {
                    awardId = column.getValue();
                }
            }

            // 再次遍历列，更新各类配置信息
            for (CanalEntry.Column column : afterColumnsList) {
                if (column.getName().equals("inventory")) {
                    // 更新库存信息
                    String awardConfigInventoryKey =  "award_config:inventory:" + awardId;
                    redisDao.set(awardConfigInventoryKey, Integer.parseInt(column.getValue()));
                }
                if (column.getName().equals("isOverSell")) {
                    // 更新是否允许超卖
                    String awardConfigIsOverSellKey =  "award_config:isOverSell:" + awardId;
                    redisDao.set(awardConfigIsOverSellKey, Integer.parseInt(column.getValue()));
                }
                if (column.getName().equals("endTime")) {
                    // 更新结束时间
                    String awardConfigEndTimeKey =  "award_config:endTime:" + awardId;
                    SimpleDateFormat formatter = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
                    Date endTime = new Date();
                    try {
                        endTime = formatter.parse(column.getValue());
                    } catch (ParseException e) {
                        throw new RuntimeException(e);
                    }
                    redisDao.set(awardConfigEndTimeKey, endTime);
                }
                if (column.getName().equals("startTime")) {
                    String awardConfigStartTimeKey = "award_config:startTime:" + awardId;
                    SimpleDateFormat formatter = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
                    try {
                        redisDao.set(awardConfigStartTimeKey, formatter.parse(column.getValue()));
                    } catch (ParseException e) {
                        throw new RuntimeException(e);
                    }
                }
                if (column.getName().equals("price")) {
                    // 更新价格
                    String awardConfigPriceKey =  "award_config:price:" + awardId;
                    redisDao.set(awardConfigPriceKey, Integer.parseInt(column.getValue()));
                }
            }
        }
    }

    /**
     * 处理用户奖品表的删除（已注释掉）
     *
     * 从行数据中获取用户ID、奖品ID等信息
     * 删除Redis中对应的缓存数据
     *
     * @param rowDatasList 行数据列表
     */
    private void handleDeleteUserAward(List<CanalEntry.RowData> rowDatasList) {
        for (CanalEntry.RowData rowData : rowDatasList) {
            List<CanalEntry.Column> beforeColumnsList = rowData.getBeforeColumnsList();
            String userId = "";
            String awardId = "";
            for (CanalEntry.Column column : beforeColumnsList) {
                if (column.getName().equals("userId")) {
                    userId = column.getValue();
                }
                if (column.getName().equals("awardId")) {
                    awardId = column.getValue();
                }
            }
            if (StringUtils.isBlank(userId) || StringUtils.isBlank(awardId)) {
                continue;
            }
            String userAwardStatusKey = "user_award:status:" + userId + ":" + awardId;
            redisDao.remove(userAwardStatusKey);
        }
    }
}
