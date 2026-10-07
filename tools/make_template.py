"""Делает пустой шаблон base.docx из отчёта-образца: оставляет стили, поля страницы,
колонтитулы; удаляет содержимое и картинки. Запуск: python tools/make_template.py <образец.docx>"""
import sys
import docx
from docx.opc.constants import RELATIONSHIP_TYPE as RT

src = sys.argv[1]
d = docx.Document(src)
body = d.element.body
for el in list(body):
    if not el.tag.endswith("sectPr"):
        body.remove(el)
part = d.part
for rid, rel in list(part.rels.items()):
    if rel.reltype == RT.IMAGE:
        part.drop_rel(rid)
d.save("ansys_report/templates/base.docx")
