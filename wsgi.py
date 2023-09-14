from threading import Timer
import webbrowser

from app import app


def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')


if __name__ == "__main__":
    Timer(0.5, open_browser).start()
    app.run()
