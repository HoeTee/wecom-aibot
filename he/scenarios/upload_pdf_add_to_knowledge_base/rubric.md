# upload_pdf_add_to_knowledge_base

人工 review 只看两件事：

- 上传 PDF 后，系统是否已经明确入库
- 用户再发“把这份文档添加到知识库”时，系统是否直接确认，而不是再次要文件

如果 assistant 再次要求“请提供文件”或“重新上传”，直接判失败。
