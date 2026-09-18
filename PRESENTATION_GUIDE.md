# 讲者提示卡 · Task 04（20 分钟）

**准备**：终端进入 `E:\Demo\multi_agent_task_demo`，调大字号。编辑器打开 README 的三张图。系统 `python` 可运行；使用已配置的 3.11 时，把 `python` 换成 `..\.python311\python.exe`，或用 `.\run_demo.cmd`。程序会快速完成，讲解时滚动终端定位标签。

**时间分配**：背景 2 分钟；主线 8 分钟；恢复对比 4 分钟；粒度与可选 LLM 3 分钟；总结和答疑 3 分钟。

## 主线：八个步骤（先运行一次，再滚动讲解）

```powershell
python main.py --mode mock --failure replan
```

| 步骤 | 我说什么 | 画面上指什么 |
|---|---|---|
| 1. User Goal | “为 50 人组织一天的 Seminar，日期固定，总预算 8000，场地最多 5000。观察目标怎样变成可执行计划。” | USER GOAL / CONFIG |
| 2. Planner | “Planner 生成任务、依赖、成功标准和恢复策略；Executor 完成自己的任务。” | 六个 TASK；initial_tasks.json 中 T2 的字段 |
| 3. HTN | “复杂任务逐层拆解：组织活动 → 场地规划 → 搜索、检查、确认。这个 primitive 列表会真正执行。” | HTN / task_tree.json。暂略粒度表，最后回来 |
| 4. DAG / Scheduler | “树说明任务由什么组成，DAG 说明谁等谁。需求先完成；场地、议程、讲者同时就绪。邀请要等三者。” | Ready wave: T2,T3,T4；T5/T6 BLOCKED |
| 5. Executor / ReAct | “Planner 做全局规划；ReAct 风格执行器处理局部观察。先给简短决策摘要，再动作、观察。” | REASON / ACT / OBSERVE；容量 PASS |
| 6. Failure | “A 容量和预算都够，但固定日期不可用。失败分类为 INVALID_PLAN。” | T2 FAILED / FAILURE DETECTED |
| 7. Replan | “重试相同请求不能解决不可用的事实，需要换计划。A 改成 B，重新验证约束。成功的议程和讲者保留，邀请继续等待。” | RECOVERY DECISION / PLAN UPDATE；Attempt 2；T5 之后才 READY |
| 8. Final Result | “B 有 55 座，场地 4800，总费用 7300。整合器验证全部上游、预算、预订和邀请一致性后产出方案。” | FINAL RESULT / final_plan.json |

## 快速对比（约 4 分钟）

```powershell
python main.py --mode mock --failure retry
python main.py --mode mock --failure rollback
```

**Retry**：“第一次查询超时，第二次仍然选 A。原策略有效，只是执行暂时失败。”指 TRANSIENT_ERROR → RETRY → Attempt 2 SUCCESS。

**Rollback**：“已经订了 A，却确认成只有 30 座。先取消，让 booking=None，再规划 B。”指 ROLLBACK；打开 run_state.json，旧 BK-001 为 cancelled，新 BK-002 为 active。审计记录保留，旧预订不再占用当前 booking。

**Reflexion 只看关键片段**：

```powershell
python main.py --mode mock --failure reflexion | Select-String 'REASON|REFLECTION|MEMORY UPDATE|STRATEGY UPDATE|PLAN UPDATE|RESULT'
```

“第一次漏了预算过滤，独立验证器拦截；记忆让 check_budget 从 False 变成 True。Retry 重复执行，Reflexion 改变策略。”新命令重置记忆，以便重复演示。

## 粒度与可选 AI（约 3 分钟）

运行 `python main.py --granularity fine`，看 GRANULARITY 表即可。三种粒度都实际执行相同的八个动作：任务数 1/3/8、调度轮数 1/3/8、事件数 21/31/56。Coarse 难以单独监督中间产物；Fine 增加交接和调度；Normal 的搜索、验证、确认边界清楚。**这是隔离微实验，主流程仍是六个任务；统计不是延迟性能跑分。**

可选执行 `python main.py --mode llm`。没有 Key 时明确提示回退，完整流程仍完成。有 Key 和模型配置时，仅任务展示描述由 LLM 增强。说明：“AI 可以参与内容生成，系统可靠性仍由 orchestration layer 保证。”课堂主线不依赖在线服务。

## 结束与答疑（约 3 分钟）

“我们得到的是 **Executable、Dependency-aware、Verifiable、Recoverable** 的任务计划：能执行、知道依赖、可验证结果、失败可恢复。清晰的任务边界、依赖与状态管理，使多个角色能够可靠合作。”

答疑速记：这是规则驱动教学 Agent，不是自主 LLM 团队；HTN 是固定方法的简化分解；ReAct 输出是决策摘要，不是隐藏思考过程；并发是 asyncio 协作式，不是多核；B 也不可用时停止，T5/T6 继续 BLOCKED；故障发生在邀请生成前，未实现已完成下游任务的通用失效传播。所有邀请和预订都是本地模拟。
