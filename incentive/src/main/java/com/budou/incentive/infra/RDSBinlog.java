package com.budou.incentive.infra;
import com.alibaba.otter.canal.client.CanalConnector;
import com.alibaba.otter.canal.client.CanalConnectors;
import com.alibaba.otter.canal.protocol.CanalEntry;
import com.alibaba.otter.canal.protocol.Message;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.redis.RedisDao;
import com.google.protobuf.ByteString;
import com.google.protobuf.InvalidProtocolBufferException;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import java.net.InetSocketAddress;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.*;

@Slf4j
@Component
public class RDSBinlog {
    private Map<String, String> errorMap = new HashMap<>();

    @Autowired
    private RedisDao redisDao;

    @PostConstruct
    private void initThread() {
        new Thread(new Runnable() {
            @Override
            public void run() {
                while (true) {
                    try {
                        initConnect();
                    } catch (Exception e) {
                        String key = "canal_connection_error";
                        if (!hasSameError(key, e.getMessage())) {
                            log.error("canal连接出错: {}", e);
                        }
                    }
                    try {
                        Thread.sleep(10000);
                    } catch (InterruptedException e) {
                    }
                }
            }
        }).start();
    }

    private void initConnect() {
        String canalIp = "localhost";
        int canalPort = 11111;
        String canalDestination = "example";
        String canalUsername = "canal";
        String canalPassword = "canal";
        CanalConnector connector = CanalConnectors.newSingleConnector(new InetSocketAddress(canalIp,
                canalPort), canalDestination, canalUsername, canalPassword);
        int batchSize = 1;//200
        try {
            connector.connect(); // 连接到canal server
            connector.subscribe(".*\\..*");
            connector.rollback(); // 回滚到未进行ack 的地方
            log.info("canal连接成功");
            while (true) {
                Message message = connector.getWithoutAck(batchSize); // 获取指定数量的数据
                long batchId = message.getId();
                int size = message.getEntries().size();
//                log.info("batchId = " + batchId + " size = " + size);
                if (batchId == -1 || size == 0) {
                    try {
                        //未获取到消息则睡眠
                        Thread.sleep(2000);
                    } catch (InterruptedException e) {
                        log.error("InterruptedException",e);
                    }
                } else {
                    try {
                        //处理消息
                        log.info("从canal接收到: {} 条消息,消息批次: {}，开始处理", size, message.getId());
                        handleMessage(message.getEntries());
                    } catch (Exception e) {
                        log.error("handleMessage exception",e);
                        connector.rollback(batchId); // 处理失败, 回滚数据
                        String key = "canal_sync_data_error";
                        String errMsg = e.getMessage();
                        if (StringUtils.isEmpty(errMsg)) errMsg = e.toString();
                        if (!hasSameError(key, errMsg)) {
                            log.error("同步数据出错: {}", e);
                        }
                        //休眠一段时间继续获取数据
                        try {
                            Thread.sleep(10000);
                        } catch (InterruptedException ex) {
                            ex.printStackTrace();
                        }
                        continue;
                    }
                }
                connector.ack(batchId); // 提交确认
            }
        } catch (Exception e){
            log.error("==========error",e);
        } finally {
            connector.disconnect();
        }
    }

    private boolean hasSameError(String key, String error) {
        String lastError = errorMap.get(key);
        if (Objects.equals(lastError, error)) {
            return true;
        }
        errorMap.put(key, error);
        return false;
    }

    private void handleMessage(List<CanalEntry.Entry> entrys) throws InvalidProtocolBufferException {
        System.out.println("RDSBinlog.handleMessage:正在解析binlog");
        for (CanalEntry.Entry entry : entrys) {
            if (entry.getEntryType() == CanalEntry.EntryType.TRANSACTIONBEGIN || entry.getEntryType() == CanalEntry.EntryType.TRANSACTIONEND) {
                continue;
            }
            //根据数据库名获取租户名
            String databaseName = entry.getHeader().getSchemaName();
            String tableName = entry.getHeader().getTableName();
            log.info("数据库: {}, 表名: {}", databaseName, tableName);
            // 获取类型
            CanalEntry.EntryType entryType = entry.getEntryType();

            // 获取序列化后的数据
            ByteString storeValue = entry.getStoreValue();
            if (CanalEntry.EntryType.ROWDATA.equals(entryType)) {
                // 反序列化数据
                CanalEntry.RowChange rowChange = CanalEntry.RowChange.parseFrom(storeValue);
                // 获取当前事件的操作类型
                CanalEntry.EventType eventType = rowChange.getEventType();

                List<CanalEntry.RowData> rowDatasList = rowChange.getRowDatasList();
                if(eventType == CanalEntry.EventType.UPDATE){
                    handleUpdate(tableName, rowDatasList);
                }else if(eventType == CanalEntry.EventType.INSERT){
                    handleInsert(tableName, rowDatasList);
                }else if(eventType == CanalEntry.EventType.DELETE){
                    handleDelete(tableName, rowDatasList);
                }
            }
        }
    }

    private void handleDelete(String tableName, List<CanalEntry.RowData> rowDatasList) {
    }

    private void handleInsert(String tableName, List<CanalEntry.RowData> rowDatasList) {
    }

    private void handleUpdate(String tableName, List<CanalEntry.RowData> rowDatasList) {
        if(tableName.equals("user_award")){
            handleUpdateUserAward(rowDatasList);
        }
        if(tableName.equals("user_currency")){
            handleUpdateUserCurrency(rowDatasList);
        }
        if (tableName.equals("award_config")){
            handleUpdateAwardConfig(rowDatasList);
        }
        if (tableName.equals("award_inventory_split")){
            handleUpdateAwardInventorySplit(rowDatasList);
        }
    }

    private void handleUpdateAwardInventorySplit(List<CanalEntry.RowData> rowDatasList) {
        for(CanalEntry.RowData rowData : rowDatasList){
            List<CanalEntry.Column> afterColumnsList = rowData.getAfterColumnsList();
            String awardInventorySplitKey = "";
            String awardConfigInventoryKey = "";
            String hashKey = "";
            Integer inventory = 0;
            for(CanalEntry.Column column : afterColumnsList){
                if(column.getName().equals("awardId")){
                    awardInventorySplitKey = "award_inventory_split:" + column.getValue();
                    awardConfigInventoryKey = "award_config:inventory:" + column.getValue();
                }
                if(column.getName().equals("inventory")){
                    inventory = Integer.valueOf(column.getValue());
                }
                if(column.getName().equals("splitId")){
                    hashKey = "splitId:" +  column.getValue();
                }
            }
            redisDao.hmSet(awardInventorySplitKey, hashKey, inventory);
            redisDao.decrement(awardConfigInventoryKey);
        }
    }

    private void handleUpdateUserCurrency(List<CanalEntry.RowData> rowDatasList) {
        for(CanalEntry.RowData rowData : rowDatasList){
            List<CanalEntry.Column> afterColumnsList = rowData.getAfterColumnsList();
            String userId = "";
            Integer currency = 0;
            for(CanalEntry.Column column : afterColumnsList){
                if(column.getName().equals("userId")){
                    userId = column.getValue();
                }
                if(column.getName().equals("currency")){
                    currency = Integer.valueOf(column.getValue());
                }
            }
            String userCurrencyKey = "user_currency:" + userId;
            redisDao.set(userCurrencyKey, currency);
        }
    }

    private void handleUpdateUserAward(List<CanalEntry.RowData> rowDatasList) {
        for(CanalEntry.RowData rowData : rowDatasList){
            List<CanalEntry.Column> afterColumnsList = rowData.getAfterColumnsList();
            String userId = "";
            String awardId = "";
            for(CanalEntry.Column column : afterColumnsList){
                if(column.getName().equals("userId")){
                    userId = column.getValue();
                }
                if(column.getName().equals("awardId")){
                    awardId = column.getValue();
                }
            }
            String userAwardStatusKey = "user_award:status:" + userId + ":" + awardId;
            for(CanalEntry.Column column : afterColumnsList){
                if (column.getName().equals("status")) {
                    redisDao.set(userAwardStatusKey, Integer.valueOf(column.getValue()));
                }
            }
        }
    }

    private void handleUpdateAwardConfig(List<CanalEntry.RowData> rowDatasList) {
        for (CanalEntry.RowData rowData : rowDatasList) {
            List<CanalEntry.Column> afterColumnsList = rowData.getAfterColumnsList();
            String awardId = "";
            for (CanalEntry.Column column : afterColumnsList) {
                if (column.getName().equals("awardId")) {
                    awardId = column.getValue();
                }
            }
            for (CanalEntry.Column column : afterColumnsList) {
                if (column.getName().equals("inventory")) {
                    String awardConfigInventoryKey =  "awardConfig:Inventory:" + awardId;
                    redisDao.set(awardConfigInventoryKey, Integer.parseInt(column.getValue()));
                }
                if (column.getName().equals("isOverSell")) {
                    String awardConfigIsOverSellKey =  "awardConfig:isOverSell:" + awardId;
                    redisDao.set(awardConfigIsOverSellKey, Integer.parseInt(column.getValue()));
                }
                if (column.getName().equals("endTime")) {
                    String awardConfigEndTimeKey =  "awardConfig:endTime:" + awardId;
                    SimpleDateFormat formatter = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
                    Date endTime = new Date();
                    try {
                        endTime = formatter.parse(column.getValue());
                    } catch (ParseException e) {
                        throw new RuntimeException(e);
                    }
                    redisDao.set(awardConfigEndTimeKey, endTime);
                }
                if (column.getName().equals("price")) {
                    String awardConfigPriceKey =  "awardConfig:endTime:" + awardId;
                    redisDao.set(awardConfigPriceKey, Integer.parseInt(column.getValue()));
                }
            }
        }
    }
}




