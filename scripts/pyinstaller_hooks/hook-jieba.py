from PyInstaller.utils.hooks import collect_data_files

# Desktop wrapping uses the default tokenizer. Its HMM tables are imported
# Python modules on CPython. Only the main dictionary is read as a data file.
datas = collect_data_files("jieba", includes=["dict.txt"])
