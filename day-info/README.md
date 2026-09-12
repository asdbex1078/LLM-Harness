# day-info · AI 技术收集池（自动化维护）

> 原则：**收集频率高，推送频率低，形成漏斗。替你消化信息，不替你生产焦虑。**

## 机制

| 环节 | 频率 | 产物 |
| --- | --- | --- |
| 收集（静默） | 每天 09:00（自动） | `pool/YYYY-MM-DD.json`（机器读）+ `.md`（人读），三档打标 |
| 周报 | 每周日 20:00（自动） | `digests/YYYY-Www.md`（必须看 + 值得看精选，15 分钟可扫完） |
| 即时提醒 | 触发式 | 只有「必须看且项目强相关」（如 X6/G6/AntV 新版本）才即时提醒，置顶在当天收集结果里 |

分级规则：

- **必须看**：重大模型发布 / 与知识图谱・Agent・X6/G6・Obsidian 直接相关；
- **值得看**：论文、新工具、教程、开源项目、博客；
- **仅存档**：其它新闻与低相关内容（只在池里存档，不进周报）。

`critical = 必须看 且 项目强相关` → 供「即时提醒」使用。

## 目录

- `pool/` 每日收集池（JSON 供机器读，MD 供人读）
- `digests/` 每周周报；`digests/raw/` 周报合并材料
- `scripts/collect.py` 收集器（零依赖，可手动跑）
- `scripts/weekly.py` 周材料合并（周报前处理）
- `scripts/daily.sh` 每日收集 + 提交（定时任务调用）
- `scripts/publish.sh` 提交助手（自动尝试 HTTPS → SSH 双通道推送）
- `state.json` 去重 / 版本比对状态（45 天去重窗口）

## 手动使用

```bash
python3 day-info/scripts/collect.py           # 收集今天的（同日重跑会合并，不重复）
python3 day-info/scripts/weekly.py            # 合并最近 7 天为周材料
bash day-info/scripts/daily.sh                # 收集 + 本地提交（+推送，若凭证就绪）
bash day-info/scripts/publish.sh "提交信息"    # 只提交/推送（周报写完后调用）
```

数据来源：arXiv（cs.AI/CL/LG/SE）、HuggingFace（hf-mirror 镜像）、GitHub（新项目搜索 + 热门活跃仓库 + antvis 版本发布）、OpenAI / DeepMind / Anthropic 博客、Hacker News、IT之家、精选技术博客 RSS。

## 推送凭证（一次性配置，二选一）

推送目标：本仓库 `day-info-for-autoclaw` 分支。两个通道任选其一即可，`publish.sh` 会自动依次尝试。

**通道 A：HTTPS + Personal Access Token（推荐，最简单）**

- 凭证文件：`/root/.openclaw-autoclaw/workspace/.secrets/git-credentials`
- 内容格式：`https://x-access-token:<TOKEN>@github.com`
- Token：GitHub 细粒度 PAT，仅勾选 `Knowrary` 仓库、权限 `Contents: Read and write`
- 也可用环境变量 `KNOWRARY_DAYINFO_CREDS` 指向其他凭证文件路径。

**通道 B：SSH + Deploy Key（密钥已生成，待添加到仓库）**

- 私钥：`/root/.openclaw-autoclaw/workspace/.secrets/github_deploy_key`
- 公钥（添加到 https://github.com/asdbex1078/Knowrary/settings/keys ，勾选 Allow write access）：

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKzB3vICRYKUQH79Td3U1S26i263ezk/099OQhi9hmpG autoclaw-dayinfo@Knowrary
```

- `~/.ssh/config` 已把 github.com 指向 `ssh.github.com:443`（本沙箱网络对 22 端口可能受限）。

> 未配置凭证时：一切照常收集并本地提交，只是不推送；配置任一通道后自动开始推送。

---

*本目录由 AutoClaw 自动化任务维护：`pool/` 与 `digests/` 以自动生成为准；手动修改请只动说明文档。*
