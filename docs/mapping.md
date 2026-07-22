# 原架构 → 本项目 逐条映射

原思路面向「数据地图检索」：给一个用户问题，检索到正确的数据表。本项目把它迁移到「学术语域写作」：给一个想法，产出学术论文语域的文本。核心不变——**AI 负责理解与判断，harness 负责可重复执行与检查，多 Agent 围绕同一份语义做对抗验证—修复—再验证**。

## 角色映射

| 原架构 | 本项目 | 职责 |
|---|---|---|
| 主 Agent | 主 Agent · Orchestrator | 调度、判断问题原因、决定重立意/重写/补料/修复/结束 |
| 出题子 Agent | 立意子 Agent | 把想法提炼为研究命题 + 验收标准（rubric，即"预期答案"） |
| 检索子 Agent | 撰写子 Agent | 只看题（想法+命题），先组织查询检索语料，再据候选成稿 |
| 修复子 Agent | 修复子 Agent | 确认语义问题后提最小修改 |
| 关键词检索引擎 | 素材检索引擎 | 在写作规范/语料库上做候选初筛，引擎给分 |
| harness | harness | 隔离、绑定、检查、限修、重测回滚、留痕 |

## 概念映射

| 原架构概念 | 本项目对应 |
|---|---|
| 真实表名（需隐藏） | 内部标识：候选编号、rubric 条目 id、提示词内部标签（不得写进正文） |
| 预期答案 | 验收标准 rubric（盲测中对撰写子 Agent 隐藏） |
| 用户问题 | 用户的想法 idea |
| 候选表 | 候选写作素材（术语规范/学术句式/结构规范/可引用背景） |
| 数据粒度、指标、限制条件 | 语域、结构要素、论证依据、术语规范 |
| 否定表达（"不要""排除"不进查询） | 想法中"不写/不涉及"的主题不进检索查询 |
| 推荐必须来自本轮候选 | 成稿的语域选择必须引用本轮返回的候选素材 |
| 澄清题 / 需要澄清 | 想法信息不足时，立意产出澄清型命题、撰写产出补料请求 |
| 表结构/生产 SQL/血缘不可改 | 研究命题、验收标准、事实数据、已判正确段落不可被修复改写 |
| 语义描述可改 | 语域表达、措辞、术语、衔接、限定语可改 |
| 重建索引 | 语料/规范更新后重建检索索引 |
| 落痕复盘 | `runs/<timestamp>/round_N.json` |

## 伪代码对应

原文：
```
retrieval_input = harness.prepare_isolated_input(full_context)   # 只保留用户问题
query_plan      = main_agent.run_fresh_child(retrieval_input)    # 全新上下文
search_result   = retrieval_engine.search(current_index, query_plan.queries)
harness.verify_binding(retrieval_input, query_plan, search_result)
assessment      = main_agent.resume_child(query_plan, search_result)
harness.verify_assessment(assessment, search_result)
decision        = main_agent.judge(question, assessment, search_result, expected_answer)
harness.verify_evidence_and_route(decision)
if decision.problem == "semantic":
    proposal = repair_agent.propose(decision, verified_facts)
    harness.apply_allowed_semantics(proposal)
    harness.validate_and_rebuild_index()
    retest = main_agent.run_fresh_child(harness.prepare_retest())
    if not harness.verify_retest(retest):
        harness.rollback()
```

本项目实现（`harness/harness.py::run_round`）：
```
spec  = llm(spec,   prepare_spec_input(idea))              # 立意：想法→命题+rubric
plan  = llm(writer, prepare_writer_plan_input(idea, spec)) # 撰写①：谋篇+查询（盲，无 rubric）
cands = retrieval_engine.search("current_index", plan.queries)
verify_binding(plan, cands)                                # 检查查询与引擎结果绑定
draft = llm(writer, prepare_writer_draft_input(...cands))  # 撰写②：据本轮候选成稿
verify_assessment(draft, cands)                            # 引用依据须来自本轮候选
check = run_full_check(draft, spec, cands)                 # 机械检查：论文味/结构/防照抄
decision = llm(orchestrator, {...rubric, draft, check})    # 盲测结束，主 Agent 判定
verify_evidence_and_route(decision, check)                 # 证据核对 + 阻止错误修复方向
if decision.problem == "semantic":
    proposal = llm(repair, {...verified_facts})            # 最小修改
    new_draft, rejected = apply_allowed_semantics(...)     # 只改允许范围
    retest_check = run_full_check(new_draft, ...)          # 重测
    if verify_retest(retest_check): 采用   else: 回滚
```

## 边界一致性原则

沿用原文「表面方向不能矛盾」的底线：修复只能改**表达层**（语域/措辞/衔接），不能改**内容层**（命题、事实、结论方向）。若某段被判定语义正确，修复不得削弱它；若没有安全且有依据的改法，修复子 Agent 返回 `can_repair=false`，交回主 Agent 另行分流（补料或重写），而不是硬改。
