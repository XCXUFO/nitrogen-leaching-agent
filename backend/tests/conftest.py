import os

# 必须在任何 src.* 模块被 import 之前注入；
# Settings() 在 src.config 模块导入期实例化，fixture 来不及。
os.environ["DEEPSEEK_API_KEY"] = "test-key-not-real"

# 隔离宿主代理变量：WSL2 中樱花猫客户端注入的 ALL_PROXY/HTTP_PROXY 可能含
# 多行非法值（见 walking-skeleton spec §7.1），openai SDK 构造时会借 httpx
# 读 env 代理，遇换行直接 raise InvalidURL。测试不应触网，全部清掉。
for _var in (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
):
    os.environ.pop(_var, None)
