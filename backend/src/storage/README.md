# storage/

持久化层。职责：

- SQLite：会话、消息、用户（MVP 匿名 session）
- Chroma：向量库的初始化与封装
- 数据访问对象（Repository）模式，隔离业务层与 ORM
