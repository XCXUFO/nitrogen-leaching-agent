# simulator/

WHCNS 仿真封装。职责：

- 定义输入 / 输出接口契约（农田参数 dict → 氮淋失时间序列）
- Mock 实现（M1~M2 阶段）
- 真实 WHCNS 调用（M3 阶段，异步任务）

依据 ADR-006：MVP 阶段先用 mock 占位，接口先稳定。
