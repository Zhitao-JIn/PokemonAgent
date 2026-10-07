"""所有数据集共享的具名读取失败。"""


class DatasetError(Exception):
    """冻结文件缺失、哈希不符、格式错误或引用无效。"""
