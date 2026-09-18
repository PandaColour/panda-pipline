"""Read-only Android screen measurements and optional design baseline."""

import math
import re


def screen_target(width=None, height=None, density=None):
    values = (width, height, density)
    if all(value is None for value in values):
        return None
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValueError('--width、--height（设备 px）与 --density（dpi）必须一起提供正整数；'
                         '目标 375×812 dp @320 dpi 应传 --width 750 --height 1624 --density 320')
    return dict(zip(('width_px', 'height_px', 'density_dpi'), values))


def screen_report(size_text, density_text, font_text, target=None):
    sizes = re.findall(r'(?:Physical|Override) size:\s*(\d+)x(\d+)', size_text)
    densities = re.findall(r'(?:Physical|Override) density:\s*(\d+)', density_text)
    width, height = map(int, sizes[-1]) if sizes else (None, None)
    density = int(densities[-1]) if densities else None
    try:
        font = 1.0 if font_text.strip() == 'null' else float(font_text.strip())
        if not math.isfinite(font) or font <= 0:
            font = None
    except ValueError:
        font = None
    actual = {'width_px': width, 'height_px': height, 'density_dpi': density}
    logical_width = round(width * 160 / density, 3) if width and density else None
    logical_height = round(height * 160 / density, 3) if height and density else None
    target_width = round(target['width_px'] * 160 / target['density_dpi'], 3) if target else None
    target_height = round(target['height_px'] * 160 / target['density_dpi'], 3) if target else None
    differences = []
    if target:
        differences = [{'field': key, 'expected': expected, 'actual': actual[key]}
                       for key, expected in target.items() if actual[key] != expected]
    warnings = []
    if not width or not height or not density:
        warnings.append('无法完整读取屏幕尺寸或密度，不可宣称匹配设计基线')
    elif differences:
        warnings.append(
            f"请求 {target['width_px']}×{target['height_px']} px @{target['density_dpi']} dpi"
            f' = {target_width:g}×{target_height:g} dp；'
            f'实际 {width}×{height} px @{density} dpi = {logical_width:g}×{logical_height:g} dp。'
            '请核对是否将设计逻辑 dp 或参考图导出像素误作设备 px；px = dp×dpi/160，'
            '参考图导出倍率不决定设备密度。不匹配不自动判 UI 失败，按既定适配规则核验。')
    if font != 1.0:
        warnings.append('字体缩放非 1.0 或未知；视觉对照须单独核对')
    return {**actual,
            'logical_width_dp': logical_width,
            'logical_height_dp': logical_height,
            'target_logical_width_dp': target_width,
            'target_logical_height_dp': target_height,
            'font_scale': font, 'target': target,
            'matches_target': (not differences) if target and width and height and density else None,
            'differences': differences, 'warnings': warnings}
