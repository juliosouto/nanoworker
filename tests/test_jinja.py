from jinja2 import Template

t = Template("{% if val %}YES{% else %}NO{% endif %}")
print("int 0:", t.render(val=0))
print("str 0:", t.render(val="0"))
print("bool False:", t.render(val=False))
