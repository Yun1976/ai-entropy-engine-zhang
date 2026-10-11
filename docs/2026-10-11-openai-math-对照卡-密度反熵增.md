# openai/math 对照卡 — 信息密度实验 × 反熵增系统（2026-10-11）

| 项 | 内容 |
|---|---|
| 日期 | 2026-10-11（Asia/Shanghai） |
| 令旨 | 将 screened openai/math 族 **直接** 接到信息密度实验与反熵增系统；优化数学算法落点 |
| 语料 | `D:\AI WORK\work\openai-math`（亦归档于端点星主库）；上游蒸馏 [[2026-10-07-openai-math-catalog-digest]] / [[2026-10-07-openai-math-applications]] |
| 符号约定（RRSI 合并框架） | \(\rho = S\cdot\lambda\cdot R\cdot C\)；\(e=u-\rho\)；\(J\) 选择目标；\(b_t\) 退火编辑预算 |
| 信任纪律 | 引用前读 `lean/docs/NNN.md` Scope；**不复制密钥/电话/PHI**；模型产出未经独立学界评审 |
| 代码落点 | `anti-entropy-runtime/density_meter.py`（钩子默认关闭） |

> **一句**：本卡把 Lean 已覆盖族的**可工程化边界**映射到 \(\rho/e/J/b_t\) 与门禁，不宣称论文全称已被本机证明。

---

## 0. 符号 ↔ 工程量速查

| 符号 | 本系统工程量 | 备注 |
|---|---|---|
| \(\rho\) | 信息密度合成（`merge_scalar.rho` / 压缩熵率代理） | 不可与单文件 `entropy_rate` 混称为同一量 |
| \(e\) | 残差 \(u-\rho\) | **仅当** `measurable_cost=true`（\|\(\Delta C\)\|>\(\varepsilon\)）才进入 \(J\) |
| \(J\) | `merge_j` 选择目标 | 含泄漏筛 / 噪声地板 / 复杂度租 / shadow prune |
| \(b_t\) | `anneal_edit_budget` | 提议端；本卡不重调 |
| 结构熵率 | `density_meter.entropy_rate = lzma(x)/\|x\|` | #113 启发的压缩代理，非精确匹配熵 \(H(x)\) |
| 新颖度 | `novelty_ngram` / `marginal_gain` | #119 侧：对语料的「保留信息」代理，非严格 \(I(f;Y)\) |

---

## 1. DIRECT density 族

### 1.1 #113 Approximate counting and entropy of perfect matchings

| 字段 | 内容 |
|---|---|
| 英文题 | Approximate counting and entropy of perfect matchings |
| Lean | `lean/docs/113.md`；Comparator：`MatchingEntropy.lean` / `MatchingEntropyBounds.lean` / `MatchingFPRAS.lean` 等 |
| Scope（摘要） | FPRAS 计完美匹配；对边际 \(x\) 证明 \(F(x)-(2-2/m)B(x)\le H(x)\le F(x)\)；保留系数-八熵界与确定性近似因子。**论文的全局 face-dimension 锐界不在形式化内** |
| → \(\rho/e/J/b_t\) | **结构熵校准**：用压缩器逼近结构熵下/上界思想 → `entropy_rate` / 语料累进 `gain_ratio` 不得系统性「看似无界可压」；烟测：条件熵式边际增益对重复灌注应趋近 0 |
| 钩子 | `density_meter`：`--math-bounds` / `MATH_BOUNDS=1` → `#113-style` 烟测（默认关） |
| 勿做 | 把 `lzma` 熵率等同于匹配熵 \(H(x)\)；勿把 FPRAS 算法原样搬进 vault 写路径 |

### 1.2 #119 Courtade–Kumar information contraction

| 字段 | 内容 |
|---|---|
| 英文题 | The Courtade–Kumar and Hellinger conjectures |
| Lean | `lean/docs/119.md`；`CourtadeKumar.lean` / `SoftChannel204.lean` |
| Scope（摘要） | 离散立方上独立对称噪声下二元信道信息锐收缩；Boolean 情形 \(I(f(X);Y)\le 1-h_2(\varepsilon)\)（比特），坐标及其补达等号。偏置细化与选定熵产不等式在内 |
| → \(\rho/e/J/b_t\) | **残差 \(e\) / 噪声门**：噪声通道后「保留互信息」有上界 → 新颖度与存活性分立；对语料的条件压缩增益在「噪声/重复」增高时应收缩。`measurable_cost` 未立时 \(e\) 不进 \(J\) |
| 钩子 | `density_meter`：`--noise-contraction` / `NOISE_CONTRACTION=1` → #119 stub（对同一笔记加噪声后边际增益应不增） |
| 勿做 | 未精读 PDF 前写入 GEO 课题定论章节 |

### 1.3 #139 log-concave query budget

| 字段 | 内容 |
|---|---|
| 英文题 | Subpolynomial query complexity for log-concave sampling |
| Lean | `lean/docs/139.md`；`LogConcaveQuery.lean` |
| Scope（摘要） | 良态 log-concave：\(V(0)=0,\nabla V(0)=0, I\le\nabla^2 V\le 2I\) 时，TV≤1/10 的最坏查询预算 \(\le C_\varepsilon d^\varepsilon\) 且最终 \(\ge c\log d\)；**算术/比特成本不界** |
| → \(\rho/e/J/b_t\) | **查询预算**：蒸馏/采样用次多项式随机查询而非全量扫描的 Complexity 依据 → `corpus_distiller` / 周更基线抽样；对应提议端勿把 \(b_t\) 当「可无限查库」 |
| 钩子 | 原则级；本轮不改 distiller 生产默认 |
| 勿做 | 把「查询次数」误写成「可忽略算力」 |

### 1.4 #140 memory–sample lower bound（LoRA / 本地适配）

| 字段 | 内容 |
|---|---|
| 英文题 | Memory–sample lower bounds for noiseless Gaussian regression |
| Lean | `lean/docs/140.md`（Scope 长；流式结果用成功率 2/3；**3/5 变体在 Scope 外**） |
| Scope（摘要） | 记忆 \(\le A d^2\) bit 时，角误差 \(\le\varepsilon\) 需 \(\ge c_A d\log(1/\varepsilon)\) 观测；\(o(d^2)\) 记忆可取万有常数 |
| → \(\rho/e/J/b_t\) | **记忆≠能力**：LoRA/本地适配只存模式不降样本需求 → 记忆层数据多样性预算独立核算；\(\rho\) 升高若靠死记则 \(e\) 与 OOD 应暴露 |
| 钩子 | 原则写入本卡 + 完成报告；不改 finetune 红线 |
| 勿做 | 用「已写入记忆层」替代样本多样性证明 |

### 1.5 #229 / #236 reconstruction thresholds（知识图聚合失真边界）

| 字段 | 内容 |
|---|---|
| #229 | Exact three- and four-state reconstruction thresholds and four-state tree capacity — Lean `229.md`；**仅 supercritical / KS 阈值之上重建**；阈值及以下非重建与 SBM 后果在 Scope 外 |
| #236 | Exact factor-of-IID threshold for free Ising on trees — Lean `236.md`；\(\tanh\beta\le 1/\sqrt{d-1}\)（含等号）时可 factor-of-IID；**有限码/码半径不在内** |
| → \(\rho/e/J/b_t\) | **聚合 fail-boundary**：多代理/知识图消息传递在树上有精确可解码阈值 → 图聚合「过噪边」应触发拒绝或降权，而非强行升 \(\rho\) |
| 钩子 | 本轮文档化阈值符号；运行时 fail-boundary 仍为手动/架构备忘 |
| 勿做 | 把 KS 阈值公式硬编码进 vault 写入路径 |

---

## 2. GATES / 原则（非 \(\rho\) 公式）

| 族 | Lean Scope 要点 | 工程门禁 | 本轮动作 |
|---|---|---|---|
| **#132** sensitivity/block sensitivity 超二次分离 | \(\mathrm{bs}/s^2\) 无界 | **l2_hard_gate**：单字段扰动通过 ≠ 块扰动安全；需组合异常注入审计 | 原则卡；不改生产闸 |
| **#245** PTS WN⇒SN | 弱归一化 ⇒ 强归一化（任意 PTS） | **RSI terminate-all-paths**：存在一条收敛路径 ≠ 所有路径收敛；改进期须声明良基终止序 | 原则卡；比对层已有 `rsi_comparators` |
| **#094** Lp 次多项式维数缩减 | \(D>1\) 时维数 \(\log n\) 级上界亚多项式 | **叙事/表示压缩天花板**：降维有代价曲线 | 原则 |
| **#087** Mahler 体积积下界 | 对称/一般 Mahler（功能不等式部分在外） | **压缩体积积叙事天花板**：过压实可能触体积积下界类比 | 原则 |
| **#273** entropy photon-number inequality（若用） | \(N(\rho_C)\ge\eta N(\rho_A)+(1-\eta)N(\rho_B)\)；热衰减/广播容量后果在外 | **cost-gated**：能量/噪声混合后熵光子数不增乱 | 建议挂 `measurable_cost` 语义旁注 |
| **#276** classical capacity of GAD（若用） | 广义振幅阻尼经典容量可加且等于 Holevo | **信道容量式成本上界** 旁注 | 同左 |

---

## 3. 红线（生产 vault）

1. `density_meter` / 钩子：**只读**输入；state.db 留痕；alerts **仅 append**；**永不写语料库 / 永不自动修 vault**。
2. 钩子默认 **OFF**；仅显式 CLI flag 或环境变量开启烟测。
3. 对照卡与报告可写 `docs/` + 主库 Science-Reports；**禁止**把 openai-math 预印本密钥、本机电话、PHI 写入开源同步面。

---

## 星云联结

- [[2026-10-07-openai-math-catalog-digest]]
- [[2026-10-07-openai-math-applications]]
- [[RRSI-反熵增映射-20261009]]
- [[DENSITY_RRSI_ABLATION_20261010]]
- [[知识库索引-MOC]]
