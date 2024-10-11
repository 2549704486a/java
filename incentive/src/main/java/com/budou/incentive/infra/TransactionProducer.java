package com.budou.incentive.infra;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
import org.apache.rocketmq.client.producer.SendStatus;
import org.apache.rocketmq.client.producer.TransactionSendResult;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.apache.rocketmq.spring.support.RocketMQHeaders;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Service;
//注解标明这是一个Spring服务组件，表示该类会被Spring管理。
@Service
public class TransactionProducer {
    //注解用于自动注入Spring容器中的RocketMQTemplate实例
    @Autowired
    private RocketMQTemplate rocketMQTemplate;
    //注解用于从Spring配置文件中读取rocketmq.topic属性值，并将其注入到topic变量中。
    @Value("${rocketmq.topic}")
    private String topic;
    /**
     * 发送事务消息
     * @param id
     * @param message
     */
    //String id: 消息ID。
    //String message: 消息内容。
    public Result sendTransactionMessage(String id, String message) {
        try{
            System.out.println("TransactionProducer.sendTransactionMessage:正在构造消息...");
            Message<String> strMessage = MessageBuilder.withPayload(message).setHeader(RocketMQHeaders.KEYS, id).build();
            TransactionSendResult result = rocketMQTemplate.sendMessageInTransaction(topic, strMessage, id);
            if (result.getSendStatus() == SendStatus.SEND_OK) {
                System.out.println("TransactionProducer.sendTransactionMessage:发送事务消息成功!消息ID为" + result.getMsgId());
                return Result.ok("发送事务消息成功!消息ID为:" + result.getMsgId());
            } else {
                return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
            }
        } catch (Exception e){
            System.out.println("TransactionProducer.sendTransactionMessage:发送事务消息时发生异常：" + e);
            return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
        }
    }
}
