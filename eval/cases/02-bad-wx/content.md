<!-- fetch_text.py schema=1 platform=wx chars=3474 -->
[¶001] AI 工具 · 方法论蒸馏 2026.09 收藏 = 学会？

[¶002] 把书、视频、播客 蒸馏 成 AI 能直接调用的技能

[¶003] RIA-TV++ 七步法 · 开源 · 25+ 现成技能包 cangjie-skill 开源AI Agent

[¶004] 📦 08 Parts + Conclusion 👉 滑动

[¶005] PART 01 为什么用不出来 收藏夹吃灰

[¶006] PART 02 它是什么 蒸馏方法论

[¶007] PART 03 解决什么痛点 压缩≠复用

[¶008] PART 04 七步蒸馏法 RIA-TV++

[¶009] PART 05 效果长什么样 技能仓库

[¶010] PART 06 宝藏技能包 现成清单

[¶011] PART 07 视频也能蒸馏 课程转写

[¶012] PART 08 蒸馏生态 nuwa·cangjie·darwin PART /// 写在最后 把看过变能用

[¶013] [图: https://mmbiz.qpic.cn/mmbiz_jpg/c2xuLcHibVdkTZQYAUxYMxiahicLKquREfhebpAl64dfibgyicpFKGI9NLyC0GgFgMc9KMbia4Yf2lIBgm6FK6jwLRFEDGKbUtkeqLebRddxyn9xU/640?wx_fmt=jpeg&from=appmsg] 你有没有过这种感觉？

[¶014] 书读了一堆、视频刷了一吨，真到要用时，脑子里还是空空如也。

[¶015] 最近 AI 圈有个挺火的想法：把一个人的经验、思维方式“蒸馏”成一个可以调用的 AI 技能。而今天要聊的 cangjie-skill（仓颉技能），走的是另一条路——它专门蒸馏“人系统性表达过的内容”：一本书、一场长访谈、一期播客、一个 B 站长视频，凡是沉淀了作者反复打磨的方法论，都能被它变成一套可独立调用、可组合、可压力测试的技能工具包。

[¶016] 它的口号很实在：读完、看完、听完之后，带走一套能调用的方法论。

[¶017] 01 PART 为什么我们“学了很多，却用不出来”

[¶018] WHY · 收藏夹吃灰

[¶019] 我们都在“收藏夹吃灰”这件事上栽过跟头。问题不在于看得少，而在于——摘要、笔记、字幕整理，只是把内容压缩了，并没有把它结构化成能复用的工具。

[¶020] 看完一本书，你往往还是不知道“什么时候该用什么”；真正值得变成工具的内容，其实只有那一小撮高价值方法论，需要严格筛选而非照单全收。

[¶021] cangjie-skill 盯着的，正是这个真实痛点：让 AI agent 能在真实场景里调用这些知识，而不是让它们躺在笔记、收藏夹和“稍后再看”里落灰。

[¶022] 02 PART cangjie-skill 到底是什么 WHAT · 蒸馏方法论

[¶023] 一句话：一个把高价值内容“蒸馏”成可调用的 AI Skills 的开源方法论 + 工具链。它不只适用于书，也适用于有字幕/转写文本的视频、播客、访谈、演讲、课程、长文和资料集。

[¶024] 只要内容里存在可抽取、可验证、可迁移的方法论，就能用 cangjie-skill 把它变成工具包。

[¶025] 官方站点 cangjie-skill.com 提供 Skill Packs 可视化浏览、从零教程与生态共建入口；GitHub 仓库仍是代码、方法论与模板的唯一来源。

[¶026] 它现在有多成熟？

[¶027] 截至 v2.5.0，项目已是一套工程化工具链：以 Capability Bundle 作为唯一事实源，支持 single 与紧凑 pack 两种确定性交付模式，并提供统一本地工具链 scripts/cangjie.py，覆盖诊断、编译、增量更新、修复、回滚、评测与基准测试。

[¶028] 03 PART 它究竟解决了哪几件事 PAIN · 压缩≠复用 知识用不起来

[¶029] 看完/听完只是“消费”，无法在真实决策里“调用”。

[¶030] 压缩 ≠ 复用

[¶031] 摘要是给人看的，不是给 agent 用的，缺的是面向执行的蒸馏。

[¶032] 内容需要筛选

[¶033] 高价值里真正能工具化的只有一小部分，得靠严格晋级而不是全收。

[¶034] 面向 agent 执行

[¶035] 现有阅读/观看方法论都面向“人”，cangjie 面向“agent 执行”。

[¶036] 04 PART

[¶037] 它是怎么工作的：RIA-TV++ 七步蒸馏法 HOW · 七步蒸馏

[¶038] 整条流水线分七个阶段，先把原始文本变成可复用的 Capability Bundle（能力包），再编译为可安装的 skill：

[¶039] 整体内容理解（Adler 分析）——借鉴 Mortimer Adler 的分析阅读法，对整份内容做结构、解释、批判、应用四步拆解，产出 BOOK_OVERVIEW.md。

[¶040] 并行提取——同时派 5 个专项提取器（框架、原则、案例、反例、术语），从原文抠出候选方法论单元。

[¶041] 三重验证 + 晋级门——候选先过证据检验，再只在使用价值足以覆盖路由成本时，晋级为独立入口。

[¶042] RIA++ 能力卡构造——把验证通过的内容按 R/I/A1/A2/E/B 写入 .cangjie/capabilities/。

[¶043] Zettelkasten 链接——把依赖、对比、组合关系写进能力图与共享术语表。

[¶044] 压力测试——为每个 skill 设计含“诱饵题”的测试用例（含跨 skill 混淆测试），不过关就回炉。

[¶045] 确定性编译与交付——同一份 Bundle 可编译为 single 或紧凑 pack，并交付 DIGEST.md、校验结果与可安装产物。

[¶046] 名字里的玄机

[¶047] RIA-TV++ 拆开看很有意思：RIA 来自赵周《这样读书就够了》的便签拆书法（Reading / Interpretation / Appropriation）；TV 是 Triple Verification，三重验证；++ 是面向 agent 执行的扩展——E（Execution 可执行步骤）+ B（Boundary 边界）。

[¶048] 既吸收验证过的阅读方法论，又把“能不能让 AI 真的去执行”当作硬指标。

[¶049] 05 PART

[¶050] 效果长什么样：从一本书到一个“技能仓库”

[¶051] EXAMPLE · 技能仓库

[¶052] 它交付的不是一篇总结文章，而是一个多 skill 仓库：

[¶053] 包含 BOOK_OVERVIEW.md 作为全局理解、INDEX.md 作为技能地图、DIGEST.md 作为精华长文、GLOSSARY.md 作为术语词典，若干 */SKILL.md 作为独立模块，以及 test-prompts.json 用于验证触发场景。

[¶054] 也就是说，当你问“这本书里讲到 XX 该怎么处理”时，对应的那个 skill 会被精准触发，而不是给你一整本复习资料。

[¶055] 06 PART 已经蒸馏出哪些“宝藏技能包”

[¶056] SHOWCASE · 现成清单

[¶057] 社区已经用 cangjie-skill 产出了大量现成技能包，下面是其中一些有代表性的： 技能包 来源 技能数

[¶058] buffett-letters-skill 巴菲特致股东的信（1957–2023） 20 duan-yongping-skill 段永平投资问答录 15

[¶059] poor-charlies-almanack-skill 《穷查理宝典》 12 contagious-skill 《疯传》 15 influence-skill 《影响力》 12

[¶060] viral-copywriting-skill 《爆款文案》 14

[¶061] huangdi-neijing-skill 《黄帝内经》 22

[¶062] first-principles-skill 《第一性原理》 10

[¶063] mao-selected-works-skill 《毛泽东选集》第 1–5 卷 25

[¶064] ai-for-everyone-skill

[¶065] 吴恩达《AI for Everyone》视频课 25 sunzi-bingfa-skill 《孙子兵法》 zhouyi-skill 《周易》

[¶066] （完整清单远超这些，覆盖投资、营销、认知、国学、数理等多个领域。） 07 PART 不止书籍：视频、课程也能蒸馏 VIDEO · 课程转写

[¶067] cangjie-skill 同样吃“视频转写文本”。仓库里已经有用吴恩达《AI for Everyone》视频课程、Loop Engineering 长视频合集蒸馏出的技能包。

[¶068] 如果要蒸馏视频，官方建议搭配 video-downloader 技能：先下载视频、提取字幕/音频转写，再把文本交给 cangjie-skill 做方法论抽取与压力测试。

[¶069] 08 PART 一个更大的“蒸馏生态”

[¶070] ECOSYSTEM · nuwa·cangjie·darwin

[¶071] cangjie-skill 不是孤品，它和另外两个项目咬合在一起： nuwa-skill 蒸馏“人”

[¶072] cangjie-skill 蒸馏“书”

[¶073] darwin-skill 持续“进化”

[¶074] nuwa 蒸馏人，cangjie 蒸馏书，darwin 让它们持续进化 LAST 写在最后 CONCLUSION · 把看过变能用

[¶075] 把“看过”变成“能用”，是这个信息过载时代最稀缺的能力之一。cangjie-skill 给出的答案很朴素也很硬核：别再满足于收藏和摘要，把高价值内容真正蒸馏成可调用的方法论。

[¶076] 如果你手里正堆着几本一直没“用起来”的书、几期没消化完的课程，不妨让它试试。

[¶077] 项目地址 https://github.com/kangarooking/cangjie-skill

[¶078] 既然看到这里了，如果觉得有用，随手点个赞、在看、转发三连吧。

[¶079] 点赞 在看 转发 THANKS FOR READING
