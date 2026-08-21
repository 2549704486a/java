package com.budou.incentive.infra;

import com.alibaba.otter.canal.protocol.CanalEntry;
import com.budou.incentive.dao.redis.RedisDao;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class RDSBinlogTest {

    @Test
    void shouldWriteUpdatedCurrencyToTheBusinessCacheKey() {
        RedisDao redisDao = mock(RedisDao.class);
        RDSBinlog binlog = new RDSBinlog();
        ReflectionTestUtils.setField(binlog, "redisDao", redisDao);

        CanalEntry.RowData rowData = CanalEntry.RowData.newBuilder()
                .addAfterColumns(column("userId", "7"))
                .addAfterColumns(column("currency", "50"))
                .build();

        ReflectionTestUtils.invokeMethod(binlog, "handleUpdateUserCurrency", List.of(rowData));

        verify(redisDao).set("user:currency:7", 50);
    }

    private CanalEntry.Column column(String name, String value) {
        return CanalEntry.Column.newBuilder()
                .setName(name)
                .setValue(value)
                .build();
    }
}
