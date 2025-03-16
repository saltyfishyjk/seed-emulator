#!/bin/bash

# 定义目标目录
TARGET_DIR="./output"

# 检查目标目录是否存在
if [ ! -d "$TARGET_DIR" ]; then
  echo "目标目录 $TARGET_DIR 不存在，请检查路径是否正确！"
  exit 1
fi

# 切换到目标目录
cd "$TARGET_DIR"

# 执行 docker-compose build 和 docker-compose up -d
echo "正在构建 Docker 镜像..."
docker-compose build

if [ $? -eq 0 ]; then
  echo "镜像构建成功，正在启动容器..."
  docker-compose up -d
else
  echo "镜像构建失败，请检查错误信息！"
  exit 1
fi

# 返回脚本执行前的目录
cd -

echo "Docker 容器已成功启动！"