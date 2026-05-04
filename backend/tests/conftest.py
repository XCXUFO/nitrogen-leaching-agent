import os

# 默认（mocked）模式下强制测试隔离：把 DEEPSEEK_API_KEY 设为哨兵值，
# 并清空 WSL2 樱花猫客户端可能注入的非法 *_PROXY 值（含换行，会让 openai
# SDK 构造时经 httpx 报 InvalidURL，见 walking-skeleton spec §7.1）。
#
# 但当 RUN_LIVE_LLM=1 时，调用方在用真实 DeepSeek 跑 smoke：必须保留
# 真实 key 与真实代理设置，否则 live 测试拿不到 key、连不上 api。
#
# 必须在任何 src.* 模块被 import 之前执行：Settings() 在 src.config
# 模块导入期实例化，fixture 来不及。
if not os.environ.get("RUN_LIVE_LLM"):
    os.environ["DEEPSEEK_API_KEY"] = "test-key-not-real"
    for _var in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    ):
        os.environ.pop(_var, None)
