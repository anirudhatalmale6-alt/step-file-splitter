# STEP File Splitter

A Python tool that splits STEP (ISO 10303-21) assembly files into individual part files, or multi-volume parts into separate volume files.

## Features

- **Assembly Splitting**: Extracts individual parts from STEP assembly files
- **Multi-Volume Part Splitting**: Splits parts containing multiple solid bodies/volumes into separate files
- **Automatic Detection**: Automatically detects whether the input is an assembly or multi-volume part
- **Entity Renumbering**: Properly renumbers entity IDs in output files
- **Preserves Geometry**: Maintains all geometric and presentation data

## Requirements

- Python 3.6 or higher (no external dependencies)

## Usage

```bash
python3 step_splitter.py <input.stp> [output_directory]
```

### Arguments

- `input.stp` - Path to the STEP file to split
- `output_directory` - Optional: Directory for output files (defaults to 'RESULT' in input file's directory)

### Examples

```bash
# Split an assembly file
python3 step_splitter.py assembly.stp

# Split a multi-volume part to a specific directory
python3 step_splitter.py part.stp ./output

# Split with default output directory
python3 step_splitter.py STEP-PART-4-VOLUME/part-4-volume.stp
```

## Supported STEP Types

### Assembly Files
Files containing `NEXT_ASSEMBLY_USAGE_OCCURRENCE` entities are detected as assemblies. Each unique part is extracted to a separate file.

### Multi-Volume Parts
Files containing multiple `MANIFOLD_SOLID_BREP` entities are detected as multi-volume parts. Each solid body is extracted to a separate file with a numeric suffix (e.g., `part_1.stp`, `part_2.stp`).

## Output

- Output files are named based on the input file or part names
- For multi-volume parts: `<original_name>_1.stp`, `<original_name>_2.stp`, etc.
- For assemblies: `<part_name>.stp`

## How It Works

1. **Parsing**: The tool parses the STEP file and builds a map of all entities
2. **Detection**: Analyzes the entity structure to determine file type (assembly or multi-volume part)
3. **Dependency Collection**: For each part/volume, collects all dependent entities (geometry, colors, styles)
4. **Writing**: Generates valid STEP files with renumbered entity IDs

## License

MIT License
