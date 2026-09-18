# 同学阅读指南：如何通过这个项目学习 Task Decomposition

这份指南帮助你理解代码背后的设计思路。第一次阅读时，不需要读完所有文件，也不需要记住所有类。建议围绕一个任务 **T2 Venue Planning**，观察它如何被创建、等待、执行、失败和恢复。

## 先记住三个主要学习点

### 1. 把复杂目标拆成可执行、可验证的子任务

用户只提出一个高层目标：

> Organize a one-day AI Agent seminar for 50 students.

Planner 将它拆成六个任务：需求分析、场地规划、议程设计、讲者安排、邀请准备和最终整合。每个任务都有负责人、输入、输出和成功标准。

学习重点：好的任务分解不只是列出待办事项，而是让每个任务都能独立执行和判断成功或失败。

### 2. 用依赖和状态控制任务的执行顺序

任务之间不是简单地从上到下执行。T1 完成后，T2、T3、T4 可以并发；T5 必须等待它们全部成功；T6 最后整合结果。

学习重点：Task Decomposition 需要和 Dependency Management 配合。任务拆出来以后，还要说明“谁必须等谁”。

### 3. 根据失败类型选择不同的恢复方式

临时超时使用 Retry；原场地不可用使用 Replan；已经产生错误预订时先 Rollback；策略遗漏预算时使用 Reflexion 更新规则。

学习重点：任务失败后不能全部使用 Retry。恢复动作应该取决于失败原因以及任务是否已经产生副作用。

## 项目整体逻辑

```text
User Goal
   ↓
Planner 拆分任务 T1—T6
   ↓
DependencyGraph 保存依赖
   ↓
Scheduler 判断 READY / BLOCKED
   ↓
Executor 执行任务
   ↓
Observation 判断成功或失败
   ↓
RecoveryManager 选择 Retry / Rollback / Replan / Reflexion
   ↓
Finalizer 检查并整合最终结果
```

## 推荐阅读顺序

不要先逐行阅读 `main.py`。按照下面的顺序阅读，更容易理解系统为什么这样设计。

### 第一步：先运行一次主线

在项目目录执行：

```powershell
.\run_demo.cmd --mode mock --failure replan
```

运行时先寻找这些标签：

```text
[PLANNER]
[DAG]
[SCHEDULER]
[REASON]
[ACT]
[OBSERVE]
[FAILURE DETECTED]
[RECOVERY DECISION]
[PLAN UPDATE]
[RESULT]
```

第一次运行只需要回答三个问题：

1. Planner 拆出了哪些任务？
2. 为什么 T5 不能提前执行？
3. Venue A 失败后，为什么系统选择 Replan？

### 第二步：阅读场地环境数据

打开 `data/venues.json`：

```json
{
  "name": "Venue A",
  "capacity": 60,
  "price": 4500,
  "available": false
}
```

这个文件代表 Executor 面对的外部环境。Planner 最初选择 Venue A，但执行时发现 `available=false`。这说明计划只是一个假设，必须经过环境验证。

请比较三个场地：

| 场地 | 容量检查 | 预算检查 | 可用性检查 | 最终判断 |
|---|---|---|---|---|
| Venue A | PASS | PASS | FAIL | 不可使用 |
| Venue B | PASS | PASS | PASS | 可以使用 |
| Venue C | FAIL | PASS | PASS | 不可使用 |

### 第三步：理解一个 Task 的数据结构

打开 `models/task.py`，再查看 `outputs/initial_tasks.json` 中的 T2。

重点字段：

| 字段 | 要回答的问题 |
|---|---|
| `task_id` | 如何唯一识别任务？ |
| `goal` | 任务要解决什么问题？ |
| `input` | 执行任务需要什么信息？ |
| `output` | 成功后产生什么结果？ |
| `dependencies` | 执行前必须等哪些任务？ |
| `status` | 当前处于哪个生命周期阶段？ |
| `success_criteria` | 如何判断任务成功？ |
| `recovery_policy` | 失败后允许如何恢复？ |
| `assigned_executor` | 哪个模块负责执行？ |

T2 可以翻译成一句自然语言：

> 在 T1 成功以后，由 VenueExecutor 为 50 人寻找符合预算和可用性要求的场地；如果失败，根据失败类型选择相应恢复策略。

### 第四步：看 Planner 如何拆任务

打开 `agents/planner.py`，重点看：

- `task_tree()`：展示 Compound Task 如何继续拆成 Primitive Tasks。
- `primitives()`：递归展开任务树。
- `PlannerAgent.plan()`：创建 T1—T6，并填写依赖、成功标准和执行者。
- `PlannerAgent.replan()`：原计划无效时，将 Venue A 替换为可行候选 Venue B。

这里可以区分两个概念：

```text
HTN / Task Tree：一个复杂任务由哪些更小任务组成？
DAG / Dependencies：这些任务按照什么顺序执行？
```

### 第五步：看依赖如何真正控制执行

打开：

- `orchestration/dependency_graph.py`
- `orchestration/scheduler.py`

重点寻找两个判断：

```text
dependencies 未全部 SUCCESS → BLOCKED
dependencies 全部 SUCCESS   → READY
```

主流程依赖如下：

```text
               ┌→ T2 Venue ───┐
T1 Requirement ├→ T3 Agenda ──┼→ T5 Invitation → T6 Final
               └→ T4 Speaker ─┘
```

当 T1 成功时，Scheduler 会把 T2、T3、T4 放进同一个 Ready Wave。它们完成以后，T5 才能执行。因此邀请不会在场地尚未确定时提前生成。

### 第六步：跟踪 T2 的实际执行

打开 `agents/venue_executor.py`。

T2 内部按照以下 Primitive Tasks 执行：

```text
Search Venue
→ Check Capacity
→ Check Availability
→ Check Budget
→ Confirm Venue
```

终端中的三个标签对应简化版 ReAct：

```text
[REASON]  简短的决策摘要
[ACT]     执行查询或约束检查
[OBSERVE] 得到环境结果
```

这里的 `[REASON]` 是教学用 Decision Summary，不是模型隐藏推理过程。

### 第七步：看失败恢复为什么不同

打开：

- `tools/mock_venue_service.py`：制造确定性的故障。
- `orchestration/recovery.py`：根据失败类型选择动作。
- `orchestration/reflection.py`：记录并使用策略经验。

比较以下命令：

```powershell
.\run_demo.cmd --mode mock --failure retry
.\run_demo.cmd --mode mock --failure replan
.\run_demo.cmd --mode mock --failure rollback
.\run_demo.cmd --mode mock --failure reflexion
```

| 模式 | 失败含义 | 恢复动作 | 是否改变策略 |
|---|---|---|---|
| retry | 查询暂时超时 | 再执行一次 | 否 |
| replan | Venue A 不可用 | 换成 Venue B | 改变候选 |
| rollback | 已产生错误预订 | 先取消，再换场地 | 撤销副作用并改计划 |
| reflexion | 策略遗漏预算条件 | 记录规则，再重新规划 | 是 |

观察时重点问：

> 原执行策略是否仍然有效？系统是否已经改变了外部状态？失败是否暴露了策略本身的问题？

这三个问题帮助 RecoveryManager 在 Retry、Rollback、Replan 和 Reflexion 之间选择。

### 第八步：看最终结果如何验证

打开：

- `agents/invitation_executor.py`
- `agents/finalizer.py`
- `outputs/final_plan.json`

InvitationExecutor 只有在场地、议程和讲者成功后才生成邀请。Finalizer 再检查：

- 是否只有一个有效预订；
- 容量和预算是否满足；
- 邀请中的场地是否与最终场地一致；
- 议程时间是否有效；
- 讲者是否覆盖所需主题。

这说明任务“完成”不等于系统“成功”。多个子任务的结果还必须能够一致地组合。

## 如何学习 Task Granularity

执行：

```powershell
.\run_demo.cmd --granularity coarse
.\run_demo.cmd --granularity normal
.\run_demo.cmd --granularity fine
```

三种模式完成相同的八个底层动作，但任务边界不同：

| 粒度 | 拆分方式 | 主要问题或优点 |
|---|---|---|
| Coarse | 一个 Handle Venue | 中间结果难监督，失败位置不清楚 |
| Normal | Search → Validate → Confirm | 输出可验证，依赖和恢复边界清晰 |
| Fine | 每个小操作都是任务 | 调度轮次和信息交接增加 |

请思考：如果一个步骤有独立产物、独立负责人、独立成功标准或独立恢复需求，它通常值得成为单独任务。

## 建议完成的三个小练习

### 练习 1：修改环境，而不是修改 Planner

把 `Venue B` 的 `available` 改为 `false`，运行 replan 模式。观察系统为什么停止，以及 T5、T6 为什么不能执行。完成后把数据改回原值。

### 练习 2：增加一个依赖

阅读 `PlannerAgent.plan()`，思考如果 Invitation 还需要等待一个新的 Catering Task，应该：

1. 新增哪个 Task？
2. 它依赖谁？
3. T5 的 dependencies 应该如何改变？
4. 谁负责执行它？

可以先画 DAG，不必立即修改代码。

### 练习 3：判断恢复策略

为下面的失败选择策略，并说明原因：

1. 场地查询第一次网络超时。
2. 场地在固定日期已经被别人占用。
3. 系统已经创建了一个容量不足的预订。
4. Planner 忘记检查预算。

参考答案依次是 Retry、Replan、Rollback 后 Replan、Reflexion 后 Replan。

## 阅读完成后的自检问题

如果你能回答下面的问题，就已经掌握了本项目的核心：

1. 为什么不能把“组织 Seminar”作为一个大任务直接执行？
2. Task Tree 和 Dependency DAG 有什么区别？
3. 为什么 T2、T3、T4 可以并发，而 T5 不可以？
4. `PENDING`、`BLOCKED`、`READY`、`RUNNING` 有什么区别？
5. 为什么 Venue A 不可用时不能只做 Retry？
6. Rollback 撤销的具体状态是什么？
7. Reflexion 和 Retry 的核心区别是什么？
8. Finalizer 为什么还需要重新验证各任务结果？

## 一句话总结

Task Decomposition 的目标不是把任务拆得越多越好，而是把复杂目标转换成一组 **可执行、依赖明确、结果可验证、失败可恢复** 的任务。
