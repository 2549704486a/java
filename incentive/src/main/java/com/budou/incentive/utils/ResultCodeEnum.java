package com.budou.incentive.utils;

public enum ResultCodeEnum {

    SUCCESS(200, "succes"),
    USERID_ERROR(501, "userIdError"),
    Query_Later(502,"queryLater"),
    AWARDID_ERROR(503, "awardIdError"),
    NOTLOGIN(504, "notLogin"),
    AWARD_REDEEMED(505, "awardRedeemed"),
    INSUFFICIENT_CURRENCY(506, "insufficientCurrency"),
    TRANSACTION_SEND_FAILED(507, "transactionSendFailed"),
    AWARD_EXPIRE(508, "awardExpire"),
    Failed(509, "Failed");

    private Integer code;
    private String message;

    ResultCodeEnum(Integer code, String message){
        this.code = code;
        this.message = message;
    }

    public Integer getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }
}
