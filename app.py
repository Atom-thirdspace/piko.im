from flask import Flask, redirect, url_for, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return "this is home page"


@app.route("/login")
def login():
     return "login page"