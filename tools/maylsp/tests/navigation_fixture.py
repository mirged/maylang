"""Generate a workspace where references and rename visit every indexed file."""
from pathlib import Path


def workspace(folder: Path, files: int):
    assert files >= 2
    folder.mkdir()
    library = folder / 'library.may'
    library.write_text('/// Shared fixture function.\npub fun shared() -> Int { return 1; }\n')
    main = folder / 'main.may'
    source = 'import "library";\nshared();\n'
    main.write_text(source)
    for index in range(files - 2):
        (folder / f'using{index:05}.may').write_text(source)
    return main, library, source
