"""Choose a project accent far from existing colors in perceptual OKLab space."""

import colorsys
import re


def _oklab(color):
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    long = (.4122214708 * r + .5363325363 * g + .0514459929 * b) ** (1 / 3)
    m = (.2119034982 * r + .6806995451 * g + .1073969566 * b) ** (1 / 3)
    s = (.0883024619 * r + .2817188376 * g + .6299787005 * b) ** (1 / 3)
    return (.2104542553 * long + .793617785 * m - .0040720468 * s,
            1.9779984951 * long - 2.428592205 * m + .4505937099 * s,
            .0259040371 * long + .7827717662 * m - .808675766 * s)


def distinct_project_color(existing):
    used = [_oklab(color) for color in existing if re.fullmatch(r"#[0-9a-fA-F]{6}", color or "")]
    if not used:
        return "#3778bd"
    candidates = []
    for hue in range(0, 360, 15):
        for saturation, value in ((.55, .9), (.65, .7), (.35, .95)):
            rgb = colorsys.hsv_to_rgb(hue / 360, saturation, value)
            candidates.append("#" + "".join(f"{round(channel * 255):02x}" for channel in rgb))

    def separation(color):
        sample = _oklab(color)
        return min(sum((a - b) ** 2 for a, b in zip(sample, other)) for other in used)

    return max(candidates, key=separation)
