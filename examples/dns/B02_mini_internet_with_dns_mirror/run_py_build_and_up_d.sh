#!/bin/bash

# 等价于在./目录下 conda activate dnshound, python mini_internet_with_dns.py 然后 ./output 目录下执行 docker-compose build && docker-compose up -d

# 激活 conda 的 dnshound 环境
echo "激活 conda 的 dnshound 环境..."

CONDA_INIT_SCRIPT="/home/yujk/miniconda3/etc/profile.d/conda.sh"

source CONDA_INIT_SCRIPT

conda activate dnshound

#if [ $? -ne 0 ]; then
#  echo "激活 conda 环境失败，请检查错误信息！"
#  exit 1
#fi

# 执行 Python 脚本
echo "执行 mini_internet_with_dns.py..."
python mini_internet_with_dns.py

if [ $? -ne 0 ]; then
  echo "执行 Python 脚本失败，请检查错误信息！"
  exit 1
fi

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