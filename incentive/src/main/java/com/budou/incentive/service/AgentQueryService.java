package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.FinishTaskRecordMapper;
import com.budou.incentive.dao.mapper.TaskConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.FinishTaskRecord;
import com.budou.incentive.dao.model.TaskConfig;
import com.budou.incentive.dao.model.UserAwardRecord;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.AwardDetailView;
import com.budou.incentive.dto.agent.AwardOptionView;
import com.budou.incentive.dto.agent.ExchangeEligibilityView;
import com.budou.incentive.dto.agent.ExchangeRecordView;
import com.budou.incentive.dto.agent.TaskOptionView;
import com.budou.incentive.dto.agent.UserPointsView;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class AgentQueryService {

    private static final String TASK_AVAILABLE = "AVAILABLE";
    private static final String TASK_COMPLETED_UNCLAIMED = "COMPLETED_UNCLAIMED";
    private static final String TASK_REWARDED = "REWARDED";

    private final UserCurrencyMapper userCurrencyMapper;
    private final TaskConfigMapper taskConfigMapper;
    private final FinishTaskRecordMapper finishTaskRecordMapper;
    private final AwardConfigMapper awardConfigMapper;
    private final UserAwardMapper userAwardMapper;

    public AgentQueryService(UserCurrencyMapper userCurrencyMapper,
                             TaskConfigMapper taskConfigMapper,
                             FinishTaskRecordMapper finishTaskRecordMapper,
                             AwardConfigMapper awardConfigMapper,
                             UserAwardMapper userAwardMapper) {
        this.userCurrencyMapper = userCurrencyMapper;
        this.taskConfigMapper = taskConfigMapper;
        this.finishTaskRecordMapper = finishTaskRecordMapper;
        this.awardConfigMapper = awardConfigMapper;
        this.userAwardMapper = userAwardMapper;
    }

    public AgentToolResponse<UserPointsView> getUserPoints(Long userId) {
        if (!isPositive(userId)) {
            return AgentToolResponse.fail("INVALID_ARGUMENT", "userId 必须为正整数", false);
        }
        Integer points = userCurrencyMapper.selectCurrency(userId);
        if (points == null) {
            return AgentToolResponse.fail("USER_NOT_FOUND", "用户不存在", false);
        }
        return AgentToolResponse.ok("POINTS_FOUND", new UserPointsView(userId, points), "积分查询成功");
    }

    public AgentToolResponse<List<TaskOptionView>> listAvailableTasks(Long userId) {
        if (!isPositive(userId)) {
            return AgentToolResponse.fail("INVALID_ARGUMENT", "userId 必须为正整数", false);
        }
        if (userCurrencyMapper.selectCurrency(userId) == null) {
            return AgentToolResponse.fail("USER_NOT_FOUND", "用户不存在", false);
        }

        Map<Long, Integer> statusByTaskId = new HashMap<>();
        for (FinishTaskRecord record : finishTaskRecordMapper.selectUserTaskRecords(userId)) {
            statusByTaskId.put(record.getTaskId(), record.getStatus());
        }

        List<TaskOptionView> tasks = taskConfigMapper.selectActiveTasks(new Date()).stream()
                .map(task -> toTaskView(task, statusByTaskId.get(task.getTaskId())))
                .filter(task -> !TASK_REWARDED.equals(task.status()))
                .toList();
        String code = tasks.isEmpty() ? "TASKS_EMPTY" : "TASKS_FOUND";
        String message = tasks.isEmpty() ? "当前没有可推荐任务" : "可用任务查询成功";
        return AgentToolResponse.ok(code, tasks, message);
    }

    public AgentToolResponse<AwardDetailView> getAwardDetail(Long awardId) {
        if (!isPositive(awardId)) {
            return AgentToolResponse.fail("INVALID_ARGUMENT", "awardId 必须为正整数", false);
        }
        AwardConfig award = awardConfigMapper.selectAwardInfo(awardId);
        if (award == null) {
            return AgentToolResponse.fail("AWARD_NOT_FOUND", "奖品不存在", false);
        }
        return AgentToolResponse.ok("AWARD_FOUND", toAwardDetail(award), "奖品查询成功");
    }

    public AgentToolResponse<List<AwardOptionView>> listAwards(Long userId, boolean redeemableOnly) {
        if (!isPositive(userId)) {
            return AgentToolResponse.fail("INVALID_ARGUMENT", "userId 必须为正整数", false);
        }
        Integer points = userCurrencyMapper.selectCurrency(userId);
        if (points == null) {
            return AgentToolResponse.fail("USER_NOT_FOUND", "用户不存在", false);
        }

        List<AwardOptionView> awards = awardConfigMapper.selectActiveAwards(new Date()).stream()
                .map(award -> toAwardOption(userId, points, award))
                .filter(award -> !redeemableOnly || award.redeemable())
                .toList();
        String code = awards.isEmpty() ? "AWARDS_EMPTY" : "AWARDS_FOUND";
        String message = awards.isEmpty() ? "当前没有符合条件的奖品" : "奖品列表查询成功";
        return AgentToolResponse.ok(code, awards, message);
    }

    public AgentToolResponse<ExchangeEligibilityView> checkExchangeEligibility(Long userId, Long awardId) {
        if (!isPositive(userId) || !isPositive(awardId)) {
            return AgentToolResponse.fail("INVALID_ARGUMENT", "userId 和 awardId 必须为正整数", false);
        }
        Integer points = userCurrencyMapper.selectCurrency(userId);
        if (points == null) {
            return AgentToolResponse.fail("USER_NOT_FOUND", "用户不存在", false);
        }
        AwardConfig award = awardConfigMapper.selectAwardInfo(awardId);
        if (award == null) {
            return AgentToolResponse.fail("AWARD_NOT_FOUND", "奖品不存在", false);
        }

        ExchangeEligibilityView eligibility = evaluateEligibility(userId, points, award, new Date());
        return AgentToolResponse.ok(eligibility.reasonCode(), eligibility, eligibility.reason());
    }

    public AgentToolResponse<List<ExchangeRecordView>> listExchangeRecords(Long userId, Long awardId) {
        if (!isPositive(userId) || (awardId != null && !isPositive(awardId))) {
            return AgentToolResponse.fail("INVALID_ARGUMENT", "userId 和 awardId 必须为正整数", false);
        }
        if (userCurrencyMapper.selectCurrency(userId) == null) {
            return AgentToolResponse.fail("USER_NOT_FOUND", "用户不存在", false);
        }

        List<ExchangeRecordView> records = userAwardMapper.selectUserAwardRecords(userId, awardId)
                .stream()
                .map(this::toExchangeRecordView)
                .toList();
        String code = records.isEmpty() ? "EXCHANGE_RECORDS_EMPTY" : "EXCHANGE_RECORDS_FOUND";
        String message = records.isEmpty() ? "当前没有兑换记录" : "兑换记录查询成功";
        return AgentToolResponse.ok(code, records, message);
    }

    private TaskOptionView toTaskView(TaskConfig task, Integer rewardStatus) {
        String status = rewardStatus == null
                ? TASK_AVAILABLE
                : (rewardStatus == 0 ? TASK_COMPLETED_UNCLAIMED : TASK_REWARDED);
        return new TaskOptionView(
                task.getTaskId(), task.getTaskName(), task.getCurrency(), task.getStartTime(), task.getEndTime(),
                task.getType(), task.getDescription(), status
        );
    }

    private AwardOptionView toAwardOption(Long userId, Integer points, AwardConfig award) {
        ExchangeEligibilityView eligibility = evaluateEligibility(userId, points, award, new Date());
        return new AwardOptionView(
                toAwardDetail(award), eligibility.eligible(), eligibility.pointsGap(), eligibility.reasonCode()
        );
    }

    private AwardDetailView toAwardDetail(AwardConfig award) {
        return new AwardDetailView(
                award.getAwardId(), award.getName(), award.getCoverUrl(), award.getAwardType(),
                award.getInventory(), award.getPrice(), award.getStartTime(), award.getEndTime(),
                Integer.valueOf(1).equals(award.getIsOverSell())
        );
    }

    private ExchangeEligibilityView evaluateEligibility(Long userId, Integer points, AwardConfig award, Date now) {
        Integer requiredPoints = award.getPrice();
        int pointsGap = Math.max(requiredPoints - points, 0);
        Integer status = userAwardMapper.selectStatus(userId, award.getAwardId());

        if (status != null && status == 0) {
            return eligibility(userId, award, false, "EXCHANGE_PROCESSING", "兑换正在处理中",
                    points, requiredPoints, pointsGap);
        }
        if (status != null && status == 1) {
            return eligibility(userId, award, false, "ALREADY_REDEEMED", "该奖品已经兑换成功",
                    points, requiredPoints, pointsGap);
        }
        if (award.getStartTime() != null && now.before(award.getStartTime())) {
            return eligibility(userId, award, false, "AWARD_NOT_STARTED", "兑换活动尚未开始",
                    points, requiredPoints, pointsGap);
        }
        if (award.getEndTime() != null && now.after(award.getEndTime())) {
            return eligibility(userId, award, false, "AWARD_EXPIRED", "兑换活动已经结束",
                    points, requiredPoints, pointsGap);
        }
        if (award.getInventory() == null || award.getInventory() <= 0) {
            return eligibility(userId, award, false, "OUT_OF_STOCK", "奖品库存不足",
                    points, requiredPoints, pointsGap);
        }
        if (points < requiredPoints) {
            return eligibility(userId, award, false, "INSUFFICIENT_POINTS", "积分不足，还差 " + pointsGap + " 积分",
                    points, requiredPoints, pointsGap);
        }
        return eligibility(userId, award, true, "ELIGIBLE", "当前满足兑换条件",
                points, requiredPoints, 0);
    }

    private ExchangeEligibilityView eligibility(Long userId, AwardConfig award, boolean eligible,
                                                String reasonCode, String reason, Integer currentPoints,
                                                Integer requiredPoints, Integer pointsGap) {
        return new ExchangeEligibilityView(
                userId, award.getAwardId(), eligible, reasonCode, reason,
                currentPoints, requiredPoints, pointsGap
        );
    }

    private ExchangeRecordView toExchangeRecordView(UserAwardRecord record) {
        String status;
        String message;
        if (record.getStatus() != null && record.getStatus() == 0) {
            status = "PROCESSING";
            message = "兑换正在处理中";
        } else if (record.getStatus() != null && record.getStatus() == 1) {
            status = "SUCCESS";
            message = "兑换成功";
        } else {
            status = "FAILED";
            message = "兑换失败";
        }
        String awardName = record.getAwardName() == null
                ? "奖品 " + record.getAwardId()
                : record.getAwardName();
        return new ExchangeRecordView(
                record.getOrderId(),
                record.getAwardId(),
                awardName,
                status,
                message,
                record.getCreateTime(),
                record.getUpdateTime()
        );
    }

    private boolean isPositive(Long value) {
        return value != null && value > 0;
    }
}
