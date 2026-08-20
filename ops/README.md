# Linux 排障与真实压测实践

本目录用于支撑 `incentive-事务消息` 项目在 Linux 云服务器上的真实压测、观测采样和面试复盘。

## 文件说明

- `exchange_load_test.py`
  - 可在 Linux 压测机或 APP 节点上直接执行
  - 复用当前秒杀项目最后一轮的压测口径
  - 自动统计 QPS、平均 RT、P50/P95/P99 和 `T+5/T+15/T+30` 异步结果
- `linux_perf_capture.sh`
  - 在 Linux 节点上采集 CPU、内存、磁盘、网络、线程和 JVM 指标
  - 适合在压测期间同时运行，形成一份节点侧证据包

## 推荐的真实实践拓扑

为了尽量接近生产环境，建议至少拆成三类节点：

1. 压测节点
   - 单独一台 Linux 机器
   - 负责向 APP 节点发压测流量
   - 不与 APP 节点复用，避免自压测污染 CPU 和网络
2. APP 节点
   - 提供秒杀受理接口
   - 负责发送事务消息
3. MQ/Consumer 节点
   - 运行 RocketMQ、Canal 与事务消息消费者

MySQL 和 Redis 继续使用云上托管实例，并通过内网访问。

## 推荐的演练顺序

### 1. 基线压测

在压测节点执行：

```bash
python3 ops/exchange_load_test.py \
  --base-url http://10.0.1.3:8088 \
  --endpoint /userAward/exchangeRedisMq \
  --award-id 6 \
  --user-start 3001 \
  --user-count 500 \
  --concurrency 50
```

同时在 APP 节点执行：

```bash
bash ops/linux_perf_capture.sh --service incentive-api --duration 90 --interval 1
```

在 MQ/Consumer 节点执行：

```bash
bash ops/linux_perf_capture.sh --service incentive-consumer --duration 90 --interval 1
```

### 2. 消费堆积演练

1. 压测前先停掉 `incentive-consumer`
2. 持续发送一轮请求
3. 观察 MQ 堆积、`result` 接口 pending 数量
4. 再恢复 `incentive-consumer`
5. 观察 `T+5/T+15/T+30` 的收敛速度

### 3. GC/内存压力演练

1. 适当降低 APP 或 Consumer JVM 堆大小
2. 重复压测
3. 重点观察：
   - `jstat -gcutil`
   - `top -H`
   - `vmstat`
   - RT 长尾

### 4. 中间件故障演练

建议至少做下面两类：

1. Redis 重连或短时不可达
2. Consumer 进程退出或重启

目标不是追求系统毫无抖动，而是验证：

- 接口如何退化
- MQ 是否会积压
- 补偿是否能收敛
- 恢复后是否能对账

## 节点侧重点指标

### APP 节点

- 接口 RT、QPS、线程占用
- GC 次数和停顿
- 与 Redis、MySQL、RocketMQ 的连接状态

### MQ/Consumer 节点

- 消费线程 CPU 占用
- `reconsumeLater` 次数
- 消费完成平均耗时
- RocketMQ 堆积和 Consumer 日志

### MySQL/Redis

- 连接数
- CPU / 内存 / IOPS
- 慢 SQL / 慢命令

## 练到什么程度算合格

至少要能做到下面这段完整表达：

> 压测时我不会只盯接口 RT，而是把应用层、JVM 层、机器层、数据库层和消息层一起看。Linux 上我会先用 `systemctl` 和 `journalctl` 确认服务状态，再用 `top`、`pidstat`、`vmstat`、`iostat`、`ss` 判断 CPU、内存、磁盘和网络是否是瓶颈；如果是 Java 进程，还会用 `jstat` 和 `jstack` 去看 GC 和线程阻塞，最后把机器指标和 MySQL、Redis、RocketMQ 的监控一起对应起来，判断瓶颈到底是在入口、消费、数据库还是中间件。`
