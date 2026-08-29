from pathlib import Path

FILES = [
    Path('iros-terminal/app/components/SigqQvtPanel.tsx'),
    Path('iros-terminal/app/components/SwotAnalysisPanel.tsx'),
    Path('iros-terminal/app/components/ConfidenceCheckerPanel.tsx'),
    Path('iros-terminal/app/components/TechnicalAnalysisPanel.tsx'),
]

HELPER = '''\nconst TRENDLYNE_DARK_FILTER = "invert(0.92) hue-rotate(180deg) brightness(0.86) contrast(1.08)";\n\nfunction forceTrendlyneIframeDark(host: HTMLElement) {\n  const apply = () => {\n    host.querySelectorAll("iframe").forEach((node) => {\n      const iframe = node as HTMLIFrameElement;\n      iframe.style.filter = TRENDLYNE_DARK_FILTER;\n      iframe.style.backgroundColor = "#ffffff";\n      iframe.style.colorScheme = "dark";\n    });\n  };\n\n  const observer = new MutationObserver(apply);\n  observer.observe(host, { childList: true, subtree: true });\n  apply();\n  return () => observer.disconnect();\n}\n'''

for path in FILES:
    text = path.read_text(encoding='utf-8')
    if 'TRENDLYNE_DARK_FILTER' not in text:
        anchor = text.find('\nexport default function ')
        if anchor == -1:
            raise SystemExit(f'No export default function anchor in {path}')
        text = text[:anchor] + HELPER + text[anchor:]

    if 'const stopTrendlyneDark = forceTrendlyneIframeDark(host);' not in text:
        target = '    host.replaceChildren();\n'
        if target not in text:
            raise SystemExit(f'No host.replaceChildren anchor in {path}')
        text = text.replace(
            target,
            target + '    const stopTrendlyneDark = forceTrendlyneIframeDark(host);\n',
            1,
        )

    cleanup_target = 'return () => host.replaceChildren();'
    if cleanup_target in text:
        text = text.replace(
            cleanup_target,
            'return () => { stopTrendlyneDark(); host.replaceChildren(); };',
            1,
        )
    elif 'stopTrendlyneDark();' not in text:
        # For multiline cleanup blocks, inject before the first host.replaceChildren in cleanup.
        cleanup_block = '    return () => host.replaceChildren();\n'
        if cleanup_block in text:
            text = text.replace(cleanup_block, '    return () => { stopTrendlyneDark(); host.replaceChildren(); };\n', 1)
        else:
            # Locate the last cleanup host.replaceChildren after the observer setup.
            idx = text.rfind('host.replaceChildren();')
            if idx == -1:
                raise SystemExit(f'No cleanup host.replaceChildren in {path}')
            text = text[:idx] + 'stopTrendlyneDark(); ' + text[idx:]

    path.write_text(text, encoding='utf-8')
    print(f'patched {path}')
