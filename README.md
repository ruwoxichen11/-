# Academic-Register Agent · 学术语域改写智能体

> 输入一个粗糙的想法，交付一段**学术论文语域**的文本——把一切写出「论文味」。
>
> 本项目把一套用于数据检索的 **Retrieval–Repair Loop**（对抗验证—修复—再验证）思想，迁移到「想法 → 学术论文文本」这一写作任务上，形成 **Draft–Critique–Repair Loop**。它同时在做 **Context Engineering、Harness Engineering 和 Loop Engineering**：
>
> - **Context Engineering**：把「想法」「已核实事实」「写作规范/语料」组织成可检索、可复用的 context，并严格控制每个环节能看到什么；
> - **Harness Engineering**：由程序保障上下文互相隔离、检索在真实语料库中执行、每轮证据可核验，并把修改限制在允许范围内；
> - **Loop Engineering**：让多个 Agent 围绕同一份「研究命题」形成「盲写—评判—修复—再验证」的循环，在真实检查中暴露语域问题、完成修复、让文本质量持续提高。

只有当 AI 的推理结果与可核对的事实冲突、且现有信息不足以支持它继续判断时，才需要人介入。

---

## 为什么不是「一个提示词直接改写」

直接给模型一段「请把它写得学术一点」的提示，问题在于：模型既出题又答题又打分，没有独立的验收基准，容易自我迎合、堆砌"研究表明""综上所述"来伪造论文味，或把你原话原样抬进正文。

本项目的做法是**把理解/判断交给 AI，把可重复执行和检查交给程序（harness）**，并用**盲测**切断自我迎合：

| 环节 | 谁来做 | 关键约束 |
|---|---|---|
| 立意（定"该达到什么"） | AI（立意子 Agent） | 只看想法与已核实事实，产出研究命题 + 验收标准（rubric） |
| 撰写（把它写出来） | AI（撰写子 Agent） | **看不到 rubric**（盲测）；先组织查询，由引擎检索语料，再据候选成稿 |
| 检索 | 程序（关键词引擎） | 引擎执行查询并给分，模型不得自填结果/排名/分数 |
| 机械检查 | 程序（harness） | 论文味评分、结构完整性、防照抄/防堆词/证据绑定 |
| 判断问题原因 | AI（主 Agent） | 盲测结束后才同时读到 rubric 与成稿；先排除想法/立意/资料问题，再定语域 |
| 修复 | AI（修复子 Agent） | 只接收已确认的语义问题，做最小修改，不得照抄 rubric、不得写入内部标识 |
| 执行修改+重测+回滚 | 程序（harness） | 只改允许范围；重测失败即回滚；全程留痕 |

---

## 架构

```
                        ┌──────────────────────────────┐
                        │      主 Agent · Orchestrator   │
                        │   调度 · 判断问题原因 · 分流     │
                        └───────┬──────────┬─────────────┘
             ┌──────────────────┘          └──────────────────┐
             ▼                              ▼                  ▼
   ┌──────────────────┐        ┌──────────────────┐  ┌──────────────────┐
   │  立意子 Agent      │        │  撰写子 Agent      │  │  修复子 Agent      │
   │ (对应 出题)        │        │ (对应 检索)         │  │ (对应 修复)         │
   │ 想法→命题+rubric   │        │ 谋篇→查询→成稿      │  │ 确认后最小修改      │
   └────────┬─────────┘        └────────┬─────────┘  └────────┬─────────┘
            └───────────────────────────┼──────────────────────┘
                                        ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                     Harness（可重复执行·可机械检查）                  │
   │  ① 上下文隔离  ② 盲测校验  ③ 两阶段检索绑定  ④ 机械检查              │
   │  ⑤ 限制修改范围  ⑥ 重测与回滚  ⑦ 全程留痕                          │
   └──────────────────────────────────────────────────────────────────┘
```

角色详细提示词见 [`agents/`](agents/)：

- [`agents/01_orchestrator.md`](agents/01_orchestrator.md) — 主 Agent（调度与判断）
- [`agents/02_spec_agent.md`](agents/02_spec_agent.md) — 立意子 Agent（对应「出题」）
- [`agents/03_writer_agent.md`](agents/03_writer_agent.md) — 撰写子 Agent（对应「检索」）
- [`agents/04_repair_agent.md`](agents/04_repair_agent.md) — 修复子 Agent（对应「修复」）

---

## 快速开始

无需任何 API Key 即可用内置 **mock 后端**跑通全流程（纯标准库）：

```bash
git clone <your-repo-url>
cd academic-register-agent
python run.py "大模型总是一本正经地胡说八道，我想搞清楚这是为啥"
```

输出会包含：研究命题、最终学术语域成稿、机械检查结果、主 Agent 判定、（如有）修复重测结论，以及本次运行的完整留痕目录 `runs/<timestamp>/`。

### 接入真实大模型

任意 OpenAI 兼容接口：

```bash
export ARA_BACKEND=openai
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1   # 或你的兼容网关
export ARA_MODEL=gpt-4o-mini
pip install openai
python run.py "远程办公到底是提高了效率还是降低了效率"
```

四个子 Agent 会分别以各自的系统提示词（`agents/*.md`）在**全新上下文**中被调用，彼此不共享历史——这正是上下文隔离的实现方式。

---

## harness 落实了哪些约束

对照原架构逐条实现（见 [`harness/`](harness/)）：

1. **上下文隔离**（`prepare_*_input`）：程序从完整资料中抽取当前环节允许看到的内容，隐藏 rubric（预期答案）、历史结果，再启动全新上下文的子 Agent。
2. **两阶段检索绑定**（`verify_binding` / `verify_assessment`）：第一阶段撰写子 Agent 只组织查询，关键词引擎（`retrieval_engine.py`）在语料索引上初筛；程序检查查询格式、次数、信息泄漏，并记录真实候选与分数。第二阶段同一子 Agent 据本轮候选成稿，程序检查推荐是否来自本轮候选、引用依据能否被找到。模型不得自填排名分数。
3. **机械检查与分流**（`checks.py` / `verify_evidence_and_route`）：论文味评分、结构要素、照抄 rubric、写入内部标识、关键词堆叠、证据绑定。若主 Agent 结论与可核对结果冲突（如判 finish 但检查未过），程序拒绝继续；想法/立意/资料的问题不得进入语义修改分支。
4. **限制修复并重新验证**（`apply_allowed_semantics` / `verify_retest`）：只允许修改语域、措辞、术语、衔接、限定语；拒绝照抄 rubric、堆词、写入内部标识、削弱原有正确语域。修改在副本分支上进行，重测失败即回滚到修改前。
5. **全程留痕**（`_persist`）：每一轮的输入、子 Agent 输出、真实检索候选、被拒绝的修改、机械检查与重测结果都保存到 `runs/<timestamp>/round_N.json`，可完整复盘「一段文字为什么被这样改」。

---

## 目录结构

```
academic-register-agent/
├── README.md
├── run.py                      # CLI 入口
├── requirements.txt            # 核心零依赖；openai 为可选
├── agents/                     # 四个角色的系统提示词（可直接复用到任意框架）
│   ├── 01_orchestrator.md
│   ├── 02_spec_agent.md
│   ├── 03_writer_agent.md
│   └── 04_repair_agent.md
├── harness/                    # 参考实现：隔离/绑定/检查/修复/留痕
│   ├── harness.py
│   ├── checks.py
│   ├── retrieval_engine.py
│   ├── llm_client.py
│   └── schema.py
├── examples/
│   ├── ideas.txt               # 示例想法
│   └── material_corpus.md      # 写作规范/语料库（检索引擎的索引源）
└── docs/
    └── mapping.md              # 原架构 → 本项目 的逐条映射
```

---

## 设计要点（对应原文三节）

**1. 限制可见信息**：各阶段独立 Prompt，只给完成当前任务所需材料。立意时不给历史与检索结果；撰写时不给 rubric；盲测结束后主 Agent 才同时读取 rubric 与成稿；修复子 Agent 只接收已确认的语义问题。需要隐藏的信息由上游（harness）直接移除，而非交给模型后再要求它"忽略"。

**2. 让 AI 完成语义推理**：查询怎样组织、成稿如何遣词、问题原因如何判断，都由 AI 完成；harness 不替模型做语义决策，只检查可核对的部分。撰写子 Agent 会正确处理否定表达（"不写""排除"的概念不进查询），并用足以区分的最少信息组织查询。

**3. 约束输出与修复**：每个 Prompt 都规定必须交付的内容（立意给命题+依据、撰写给查询思路并在成稿/澄清间选择、判断给原因与下一步、修复给改哪里+依据+影响范围）。修复保留已有正确描述，不把 rubric 原句或内部标识写进正文，不为通过当前检查而堆词。

详见 [`docs/mapping.md`](docs/mapping.md)。

## License

MIT，见 [`LICENSE`](LICENSE)。
