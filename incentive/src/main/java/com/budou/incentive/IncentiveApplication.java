package com.budou.incentive;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
//复合注解，结合了@Configuration、@EnableAutoConfiguration和@ComponentScan。
//参数指定要扫描的包路径，即com.budou.incentive，这样Spring Boot会扫描并加载该包中的所有组件（如@Controller、@Service、@Repository等）。
@SpringBootApplication(scanBasePackages = {"com.budou.incentive"}) // 指定要扫描的包路径
//用于扫描MyBatis的Mapper接口
//value 参数指定Mapper接口所在的包路径，即com.budou.incentive.dao.mapper，这样Spring Boot会扫描并注册该包中的所有Mapper接口。
@MapperScan(value = "com.budou.incentive.dao.mapper")
//定义一个名为IncentiveApplication的公共类，这是Spring Boot应用程序的主类。
public class IncentiveApplication {

    public static void main(String[] args) {
        //SpringApplication.run 方法启动Spring Boot应用程序。
        //参数 IncentiveApplication.class 指定主类，args 参数传递命令行参数。
        SpringApplication.run(IncentiveApplication.class);
    }

}
