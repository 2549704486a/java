package com.budou.incentive.utils;

/**
 * @program: springboot-headline
 * @description: 全局统一返回结果类
 * @author: 阿伟
 * @create: 2024-09-17 09:37
 **/
public class Result<T> {
    //返回码
    private Integer code;
    //返回信息
    private String message;
    //返回数据
    private T data;

    protected static <T> Result<T> build(T data){
        Result<T> result = new Result<>();
        if(data != null){
            result.setData(data);
        }
        return result;
    }

    public static <T> Result<T> build(T body, Integer code, String message){
        Result<T> result = Result.build(body);
        result.setCode(code);
        result.setMessage(message);
        return result;
    }

    public static <T> Result<T> build (T body, ResultCodeEnum resultCodeEnum){
        Result<T> result = Result.build(body);
        result.setCode(resultCodeEnum.getCode());
        result.setMessage(resultCodeEnum.getMessage());
        return result;
    }

    public static <T> Result<T> fail(T data){ return  build(data, ResultCodeEnum.Failed);}

    public static <T> Result<T> ok(T data){
        return build(data, ResultCodeEnum.SUCCESS);
    }

    public Result<T> message(String msg){
        this.setMessage(msg);
        return this;
    }

    public Result<T> code(Integer code){
        this.setCode(code);
        return this;
    }

    public Integer getCode() {return code;}
    public void setCode(Integer code) {this.code = code;}
    public String getMessage() {return message;
    }public void setMessage(String message) {this.message = message;}
    public T getData() {return data;}
    public void setData(T data) {this.data = data;}
}
