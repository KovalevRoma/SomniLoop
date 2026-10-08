"""Semantic colors for quiet surfaces, categories and explicit urgency."""


def workspace_stylesheet(theme):
    p = ({
        "surface": "#f2f5f9", "row": "#fafcff", "border": "#d9e1ec",
        "text": "#203149", "muted": "#52647b", "hover": "#eaf0f8",
        "blue": "#295caa", "blue_bg": "#e7effd", "teal": "#176c64", "teal_bg": "#e6f4ef",
        "violet": "#7050a6", "violet_bg": "#f0eaf9", "amber": "#84530b", "amber_bg": "#fff2d9",
        "red": "#a32c40", "red_bg": "#fce8ed", "neutral": "#edf1f6",
    } if theme == "light" else {
        "surface": "#141c27", "row": "#1d2938", "border": "#34455b",
        "text": "#e5edf9", "muted": "#b0bfd4", "hover": "#2a3a50",
        "blue": "#a5c8ff", "blue_bg": "#243957", "teal": "#91ddc9", "teal_bg": "#203d39",
        "violet": "#cdb3f5", "violet_bg": "#352d49", "amber": "#f1cd83", "amber_bg": "#433923",
        "red": "#ffb1bf", "red_bg": "#4b2b38", "neutral": "#273347",
    })
    css = f"""
    QWidget#dashboardSurface {{ background: {p['surface']}; }}
    QWidget#workSpace, QWidget#workFilters, QWidget#workList, QWidget#workControls,
    QTabBar#workspaceTabs {{ background: transparent; }}
    QWidget#workSpace QLabel {{ color: {p['text']}; background: transparent; }}
    QWidget#workSpace QLabel#muted, QWidget#workSpace QLabel#workSummary {{ color: {p['muted']}; }}
    QFrame#workRow {{ background: {p['row']}; border: 1px solid {p['border']};
        border-radius: 12px; }}
    QWidget#workSpace QLabel#cardTitle {{ font-size: 16px; font-weight: 600; }}
    QWidget#workSpace QLabel#workSummary {{ padding: 8px 12px; background: {p['neutral']}; border-radius: 8px; }}
    QWidget#dashboard QLineEdit, QWidget#dashboard QComboBox {{ background: {p['row']}; border-color: {p['border']}; }}
    QWidget#workSpace QLineEdit:focus, QWidget#workSpace QComboBox:focus {{ border-color: {p['blue']}; }}
    QWidget#workSpace QLineEdit#workCapture {{ background: {p['neutral']}; }}
    QWidget#workSpace QCheckBox {{ background: transparent; border: none; padding: 0; spacing: 0; }}
    QWidget#workSpace QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {p['muted']}; border-radius: 5px; background: {p['row']}; }}
    QWidget#workSpace QCheckBox::indicator:checked {{ background: {p['teal']}; border-color: {p['teal']}; }}
    QWidget#workSpace QPushButton {{ background: {p['row']}; color: {p['muted']};
        border: 1px solid {p['border']}; padding: 6px 10px; border-radius: 8px; }}
    QWidget#workSpace QPushButton:hover {{ background: {p['hover']}; color: {p['text']}; border-color: {p['blue']}; }}
    QWidget#workSpace QPushButton#primary {{ background: #6554c0; color: #ffffff;
        border-color: #6554c0; font-weight: 600; }}
    QWidget#workSpace QPushButton#primary:hover {{ background: #5443ad; color: #ffffff; }}
    QWidget#workSpace QPushButton:checked {{
        background: {p['blue_bg']}; color: {p['blue']}; border-color: {p['blue']}; font-weight: 600; }}
    QWidget#workSpace QPushButton:disabled {{ color: {p['muted']}; background: {p['neutral']}; border-color: {p['border']}; }}
    QWidget#workSpace QPushButton:focus {{ border: 2px solid {p['blue']}; }}
    QTabBar#workspaceTabs::tab {{ background: transparent; color: {p['muted']};
        padding: 8px 12px; margin-right: 6px; border-radius: 9px; border: 1px solid transparent; }}
    QTabBar#workspaceTabs::tab:hover {{ background: {p['hover']}; color: {p['text']}; }}
    QTabBar#workspaceTabs::tab:selected {{ background: {p['blue_bg']}; color: {p['blue']};
        border-color: {p['blue']}; font-weight: 600; }}
    QWidget#dashboard QFrame#panel {{ background: {p['row']}; border-color: {p['border']}; }}
    QWidget#dashboard QFrame#card {{ background: {p['violet_bg']}; border-color: {p['border']}; }}
    QWidget#dashboard QFrame#card[oneOffTask="true"] {{ background: {p['blue_bg']}; border-color: {p['border']}; }}
    """
    for kind, color in (("project", "teal"), ("habit", "violet"), ("inbox", "amber")):
        css += f"""
        QFrame#workRow[category="{kind}"] {{ background: {p[color + '_bg']}; }}
        QTabBar#workspaceTabs[section="{kind}"]::tab:selected {{ background: {p[color + '_bg']};
            color: {p[color]}; border-color: {p[color]}; }}
        """
    for tone, color in (("overdue", "red"),):
        css += f"""
        QWidget#workSpace QLabel[badge="{tone}"] {{ background: {p[color + '_bg']}; color: {p[color]};
            border: none; border-radius: 6px; padding: 3px 7px; font-size: 12px; font-weight: 600; }}
        """
    css += f"""
    QWidget#workSpace QPushButton#newProject {{ background: transparent; color: {p['muted']}; border: 1px solid {p['border']}; border-radius: 20px; padding: 0; font-size: 26px; font-weight: 400; }}
    QWidget#workSpace QPushButton#newProject:hover {{ background: {p['hover']}; border-color: {p['muted']}; }}
    QWidget#workSpace QPushButton#newProject:focus {{ border: 2px solid {p['blue']}; }}
    QWidget#workSpace QProgressBar {{ background: {p['border']}; border: none; border-radius: 3px; }}
    QWidget#workSpace QProgressBar::chunk {{ background: {p['teal']}; border-radius: 3px; }}
    """
    return css
