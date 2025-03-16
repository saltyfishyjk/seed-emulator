#!/bin/bash
# 等价于在 ./output 目录下执行 docker-compose down

# 定义目标目录
TARGET_DIR="./output"

# 检查目标目录是否存在
if [ ! -d "$TARGET_DIR" ]; then
  echo "目标目录 $TARGET_DIR 不存在，请检查路径是否正确！"
  exit 1
fi

# 切换到目标目录
cd "$TARGET_DIR"

# 执行 docker-compose down
echo "正在停止并移除 Docker 容器和网络..."
docker-compose down

if [ $? -eq 0 ]; then
  echo "Docker 容器和网络已成功移除！"
else
  echo "执行 docker-compose down 时出错，请检查错误信息！"
  exit 1
fi

# 返回脚本执行前的目录
cd -