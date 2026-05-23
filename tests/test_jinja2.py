from flask import Flask, render_template_string
app = Flask(__name__)
@app.route('/')
def home():
    m = {'text_output': None}
    template = """
    {% if m.text_output|int > 0 %}Text{% else %}Hidden{% endif %}
    """
    return render_template_string(template, m=m)
if __name__ == '__main__':
    with app.app_context():
        print(home())
