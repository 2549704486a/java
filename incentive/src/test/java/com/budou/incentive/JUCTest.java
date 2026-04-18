package com.budou.incentive;

import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.LockSupport;
import java.util.concurrent.locks.ReentrantLock;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-14 13:16
 **/
public class JUCTest {
    private Lock lock = new ReentrantLock();
    private LockSupport lockSupport;
}
