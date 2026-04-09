# upload_duplicate_pdf_notice

人工 review 只看两件事：

- 第二次上传内容完全一致的 PDF 时，系统是否明确说出了“重复”或“内容一致”
- 系统是否避免了重复入库

如果 assistant 没有明确指出重复，或者把重复文件当成新文件写入，直接判失败。
