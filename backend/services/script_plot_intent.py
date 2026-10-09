"""Recognize user-authored static plotting requests without consuming document text."""

import re


def wants_plot_execution(message: str) -> bool:
    text = str(message or "").strip()
    if re.search(
        r"^(?:请问)?(?:如何|怎么|怎样|是否|有没有)|^\s*(?:how\b|explain\b)",
        text,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        r"(?:不要|不需要|无需|别).{0,6}(?:执行|运行)|(?:仅|只).{0,6}(?:代码|脚本)|\b(?:do not|don't)\s+(?:run|execute)|\bcode\s+only\b",
        text,
        re.IGNORECASE,
    ):
        return False
    return bool(
        re.search(
            r"(?:画|绘制|绘图|生成).{0,24}(?:爱心|心形|曲线|图表|折线图|柱状图|散点图|饼图|函数图|图像)|"
            r"(?:绘图|画图|画爱心|画心形).{0,12}(?:脚本|代码|程序)|"
            r"\b(?:draw|plot|render|generate)\b.{0,40}\b(?:heart|chart|graph|plot)\b",
            text,
            re.IGNORECASE,
        )
    )


PLOT_INSTRUCTIONS = """
Static plotting requests require actual Python execution and a saved image, unless the user asks for code only or explicitly forbids execution.
Use python_execute for generated plotting code. The image has matplotlib, numpy and Pillow, with MPLBACKEND=Agg. Save PNG/JPEG under /output (for example /output/heart.png); close figures after saving. Do not use turtle, GUI windows, plt.show(), browsers or network installation. No selected host workspace is needed for self-contained plots. The runtime exports the original Python source for download automatically.
Use sandbox receipts and output_files to describe results; never invent file IDs, download URLs or claim an image exists before execution. If execution fails, inspect the bounded error and correct the code within the remaining tool budget. If the user explicitly asks to save to a local folder, use the existing workspace permissions and confirmation flow.
"""
