from __future__ import annotations

DARK_STYLE = r"""
QWidget {
    background: #11121a;
    color: #f2f0ff;
    font-family: Inter, "Noto Sans", sans-serif;
    font-size: 14px;
}
QWidget#flat { background: transparent; }
QLabel#homePriority { background: #36394b; color: #e2e2ef; padding: 3px 7px; border-radius: 8px; }
QPushButton#partialButton:checked { background: #67522b; border-color: #bd9b58; }
QMainWindow, QDialog { background: #11121a; }
QLabel { background: transparent; }
QCheckBox { background: transparent; spacing: 8px; }
QFrame#topBar, QFrame#card, QFrame#panel {
    background: #1a1c28;
    border: 1px solid #292c3d;
    border-radius: 14px;
}
QLabel#appTitle { font-size: 28px; font-weight: 800; color: #f8f7ff; }
QLabel#pageTitle { font-size: 22px; font-weight: 700; }
QLabel#sectionTitle { font-size: 17px; font-weight: 700; color: #dcd8ff; }
QLabel#cardTitle { font-size: 16px; font-weight: 700; }
QLabel#muted { color: #9da0b5; }
QLabel#attention {
    background: #3a2630; color: #ff859e; border-radius: 9px;
    padding: 4px 8px; font-weight: 700;
}
QPushButton {
    background: #26293a;
    border: 1px solid #35394e;
    border-radius: 9px;
    padding: 8px 12px;
    color: #f2f0ff;
}
QPushButton:hover { background: #303449; border-color: #6f62c5; }
QPushButton:pressed { background: #202230; }
QPushButton#primary { background: #715ee8; border-color: #8979ef; font-weight: 700; }
QPushButton#primary:hover { background: #806def; }
QPushButton:checked { background: #715ee8; border-color: #8979ef; color: white; }
QPushButton#danger { color: #ff8399; border-color: #643343; }
QPushButton#quickMissed { color: #ff8399; padding: 3px 9px; }
QPushButton#quickMissed:checked { background: #733444; border-color: #ee6b84; }
QLabel#quickTitle { color: #dcd8ff; font-weight: 700; margin-top: 5px; }
QPushButton#doneButton:checked { background: #1f6c53; border-color: #45c58e; }
QPushButton#notDoneButton:checked { background: #733444; border-color: #ee6b84; }
QPushButton#unsetButton:checked { background: #6e5b22; border-color: #e3bb4d; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit, QListWidget {
    background: #171925;
    border: 1px solid #34374a;
    border-radius: 8px;
    padding: 7px;
    selection-background-color: #715ee8;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDateEdit:focus { border-color: #806def; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #151721; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3b3e50; border-radius: 5px; min-height: 30px; }
QToolTip { background: #292c3d; color: white; border: 1px solid #4b506b; }
QCalendarWidget QWidget { alternate-background-color: #171925; }
QCalendarWidget QAbstractItemView:enabled { selection-background-color: #715ee8; }
QGroupBox { border: 1px solid #303347; border-radius: 10px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QTabBar::tab { background: #1a1c28; padding: 9px 15px; border-radius: 8px; margin-right: 4px; }
QTabBar::tab:selected { background: #715ee8; }
"""


LIGHT_STYLE = r"""
QCheckBox { background: transparent; spacing: 8px; }
QWidget#flat { background: transparent; }
QLabel#homePriority { background: #e5e7ef; color: #363d53; padding: 3px 7px; border-radius: 8px; }
QPushButton#partialButton:checked { background: #f2ddb6; color: #63491c; border-color: #ac8744; }
QWidget {
    background: #f5f4fa;
    color: #222332;
    font-family: Inter, "Noto Sans", sans-serif;
    font-size: 14px;
}
QMainWindow, QDialog { background: #f5f4fa; }
QLabel { background: transparent; }
QFrame#topBar, QFrame#card, QFrame#panel {
    background: white; border: 1px solid #ddd9eb; border-radius: 14px;
}
QLabel#appTitle { font-size: 28px; font-weight: 800; color: #28243c; }
QLabel#pageTitle { font-size: 22px; font-weight: 700; }
QLabel#sectionTitle { font-size: 17px; font-weight: 700; }
QLabel#cardTitle { font-size: 16px; font-weight: 700; }
QLabel#muted { color: #6e7080; }
QLabel#attention { background: #ffe3e8; color: #a92d48; border-radius: 9px; padding: 4px 8px; font-weight: 700; }
QPushButton { background: #eeebf8; border: 1px solid #d6d0ea; border-radius: 9px; padding: 8px 12px; }
QPushButton:hover { background: #e3ddf8; border-color: #806def; }
QPushButton#primary { background: #715ee8; color: white; border-color: #715ee8; font-weight: 700; }
QPushButton:checked { background: #715ee8; border-color: #715ee8; color: white; }
QPushButton#danger { color: #b3304b; border-color: #e5a8b4; }
QPushButton#quickMissed { color: #b3304b; padding: 3px 9px; }
QPushButton#quickMissed:checked { background: #ffd1da; border-color: #d74d69; color: #8d2339; }
QLabel#quickTitle { color: #51496f; font-weight: 700; margin-top: 5px; }
QPushButton#doneButton:checked { background: #b9efd9; border-color: #309d70; }
QPushButton#notDoneButton:checked { background: #ffd1da; border-color: #d74d69; }
QPushButton#unsetButton:checked { background: #ffe7a3; border-color: #c99d1f; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDateEdit, QListWidget {
    background: white; border: 1px solid #d7d3e3; border-radius: 8px; padding: 7px;
    selection-background-color: #806def;
}
QScrollArea { border: none; background: transparent; }
QGroupBox { border: 1px solid #ddd9eb; border-radius: 10px; margin-top: 12px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QTabBar::tab { background: #e9e6f2; padding: 9px 15px; border-radius: 8px; margin-right: 4px; }
QTabBar::tab:selected { background: #715ee8; color: white; }
"""


def stylesheet(theme: str) -> str:
    base = LIGHT_STYLE if theme == "light" else DARK_STYLE
    extra = """
    QWidget#windowContent { background: transparent; }
    QComboBox::drop-down {
        subcontrol-origin: padding; subcontrol-position: top right;
        width: 24px; border: none; background: transparent;
        border-top-right-radius: 8px; border-bottom-right-radius: 8px;
    }
    QWidget#datePicker { background: transparent; }
    QWidget#datePicker QSpinBox, QWidget#datePicker QComboBox, QTimeEdit#timePicker {
        border-radius: 13px; min-height: 22px; padding: 7px 10px;
        border: 1px solid #8171ad; background: #29253e; color: #f2f0ff;
    }
    QWidget#datePicker QComboBox::drop-down { border: none; width: 0px; }
    QWidget#datePicker QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
    QWidget#datePicker QPushButton { border-radius: 13px; }
    QTimeEdit#timePicker:disabled { color: #9394a8; }
    QFrame#notificationDrawer { border: 1px solid #9c8adb; border-radius: 16px; padding: 6px; }
    QLabel#timestamp { color: rgba(128, 126, 150, 175); font-size: 12px; }
    QLabel#weekNumber { background: rgba(128, 126, 150, 25); color: #92909f; border-radius: 8px; padding: 6px; }
    QProgressBar { border: none; border-radius: 5px; max-height: 10px; background: #ddd7ef; }
    QProgressBar::chunk { background: #806def; border-radius: 5px; }
    QToolTip {
        background-color: #30283f; color: #f5efff; border: 1px solid #9a87bb;
        border-radius: 8px; padding: 8px 10px; font-size: 13px; opacity: 255;
    }
    QSplitter::handle { background: transparent; width: 8px; }
    """
    extra += (
        "QFrame#notificationDrawer { background: #eee8ff; } QToolTip {background-color:#eee5fa; color:#30243f; border-color:#ab94c7;}"
        if theme == "light"
        else "QFrame#notificationDrawer { background: #252038; }"
    )
    # Static accent gradients keep the dashboard calm and add no animation timers.
    home = """
    QWidget#dashboardSurface {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #19162c, stop:0.55 #141e2d, stop:1 #122b2b);
    }
    QWidget#dashboard QFrame#panel {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #2c2447, stop:0.55 #242c40, stop:1 #203c3b);
        border-color: #655784;
    }
    QWidget#dashboard QFrame#card {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #503369, stop:0.5 #423c78, stop:1 #284e65);
        border-color: #aa83df;
    }
    QWidget#dashboard QFrame#card[oneOffTask="true"] {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #573450, stop:1 #514329);
        border-color: #c39291;
    }
    QLabel#dashboardDate { font-size: 18px; font-weight: 600; color: #d6d4fa; }
    QWidget#dashboard QLabel#muted { color: #bdc6db; }
    QWidget#dashboard QLineEdit, QWidget#dashboard QComboBox {
        background: #262b44; border-color: #6c6388;
    }
    QWidget#dashboard QFrame#card:hover { border-color: #8379b1; }
    QWidget#dashboard QPushButton#primary {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7967e4, stop:1 #585ac4);
        border: 1px solid #ac9cf9;
    }
    QWidget#dashboard QProgressBar { background: #303447; }
    QWidget#dashboard QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a28aef, stop:1 #65cbbb);
    }
    QWidget#dashboard QPushButton#completionToggle {
        padding: 3px 10px; background: #254b48; color: #e1fff3; border: 1px solid #79cdb3;
    }
    QWidget#dashboard QPushButton#completionToggle:checked {
        background: #244d46; color: #d9fff0; border-color: #74cbb0;
    }
    QWidget#dashboard QPushButton#completionToggle:hover { background: #30554e; }
    QWidget#dashboard QPushButton:focus { border: 2px solid #b4a5ff; }
    """
    if theme == "light":
        home += """
        QWidget#datePicker QSpinBox, QWidget#datePicker QComboBox, QTimeEdit#timePicker {
            background: #e5d9fa; color: #302548; border-color: #aa90d5;
        }
        QTimeEdit#timePicker:disabled { color: #6d6680; }
        QLabel#dashboardDate { color: #514076; }
        QWidget#dashboardSurface {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #e3d9f7, stop:0.55 #dce7f5, stop:1 #ceeee6);
        }
        QWidget#dashboard QFrame#panel {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #ece2ff, stop:0.55 #e0eafa, stop:1 #d8f4eb);
            border-color: #b8a0df;
        }
        QWidget#dashboard QFrame#card {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #d4b6ff, stop:0.5 #cbbff8, stop:1 #b6dfef);
            border-color: #9671ce;
        }
        QWidget#dashboard QFrame#card[oneOffTask="true"] {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #f4bddd, stop:1 #f5d49d);
            border-color: #cb98a2;
        }
        QWidget#dashboard QLabel#muted { color: #505a74; }
        QWidget#dashboard QLineEdit, QWidget#dashboard QComboBox {
            background: #e8def8; border-color: #b3a0d1;
        }
        QWidget#dashboard QFrame#card:hover { border-color: #9b86c9; }
        QWidget#dashboard QProgressBar { background: #e2deef; }
        QWidget#dashboard QPushButton#completionToggle {
            background: #bcebdc; color: #234f44; border-color: #5d9e89;
        }
        QWidget#dashboard QPushButton#completionToggle:checked {
            background: #8bdbbd; color: #194934; border-color: #46896e;
        }
        QWidget#dashboard QPushButton#completionToggle:hover { background: #cceade; }
        QWidget#dashboard QPushButton:focus { border: 2px solid #7962b7; }
        """
    return base + extra + home
