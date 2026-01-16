#!/usr/bin/env python3
"""
STEP File Splitter
==================
Splits STEP (ISO 10303-21) assembly files into individual part files,
or multi-volume parts into separate volume files.

Usage:
    python3 step_splitter.py <input.stp> [output_directory]

Author: Anirudha
"""

import re
import os
import sys
from datetime import datetime
from collections import OrderedDict
from typing import Dict, Set, List, Tuple, Optional


class StepEntity:
    """Represents a STEP entity with its ID, type, and content."""

    def __init__(self, entity_id: int, entity_type: str, content: str, full_line: str):
        self.id = entity_id
        self.type = entity_type
        self.content = content
        self.full_line = full_line
        self.references = self._parse_references(full_line)

    def _parse_references(self, line: str) -> Set[int]:
        """Extract all entity references (#xxx) from the line."""
        refs = set()
        for match in re.finditer(r'#(\d+)', line):
            refs.add(int(match.group(1)))
        # Remove self-reference
        refs.discard(self.id)
        return refs

    def __repr__(self):
        return f"StepEntity(#{self.id}, {self.type})"


class StepParser:
    """Parser for STEP (ISO 10303-21) files."""

    def __init__(self):
        self.header = ""
        self.entities: Dict[int, StepEntity] = OrderedDict()
        self.original_filename = ""

    def parse(self, filepath: str) -> None:
        """Parse a STEP file and extract all entities."""
        self.original_filename = os.path.splitext(os.path.basename(filepath))[0]

        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        # Extract header
        header_match = re.search(r'HEADER;(.*?)ENDSEC;', content, re.DOTALL)
        if header_match:
            self.header = header_match.group(1)

        # Extract DATA section
        data_match = re.search(r'DATA;(.*?)ENDSEC;', content, re.DOTALL)
        if not data_match:
            raise ValueError("Invalid STEP file: DATA section not found")

        data_section = data_match.group(1)
        self._parse_entities(data_section)

    def _parse_entities(self, data_section: str) -> None:
        """Parse all entities from the DATA section."""
        # Normalize whitespace but preserve string contents
        current_entity = []
        paren_depth = 0
        in_entity = False

        for line in data_section.split('\n'):
            line = line.strip()
            if not line:
                continue

            if not in_entity and line.startswith('#'):
                in_entity = True
                current_entity = [line]
                paren_depth = line.count('(') - line.count(')')
            elif in_entity:
                current_entity.append(line)
                paren_depth += line.count('(') - line.count(')')

            if in_entity and paren_depth <= 0 and ';' in line:
                entity_str = ' '.join(current_entity)
                self._parse_entity_line(entity_str)
                in_entity = False
                current_entity = []
                paren_depth = 0

    def _parse_entity_line(self, line: str) -> None:
        """Parse a single entity line."""
        # Match pattern: #id=TYPE(content);
        match = re.match(r'#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*)\)\s*;', line, re.DOTALL)
        if match:
            entity_id = int(match.group(1))
            entity_type = match.group(2)
            content = match.group(3)
            self.entities[entity_id] = StepEntity(entity_id, entity_type, content, line)
        else:
            # Handle complex entity types (like (TYPE1()TYPE2()TYPE3()))
            match = re.match(r'#(\d+)\s*=\s*\((.*)\)\s*;', line, re.DOTALL)
            if match:
                entity_id = int(match.group(1))
                content = match.group(2)
                # Extract first type name
                type_match = re.search(r'([A-Z_0-9]+)', content)
                entity_type = type_match.group(1) if type_match else "COMPLEX"
                self.entities[entity_id] = StepEntity(entity_id, entity_type, content, line)

    def find_entities_by_type(self, entity_type: str) -> List[int]:
        """Find all entity IDs of a specific type."""
        return [eid for eid, entity in self.entities.items() if entity.type == entity_type]

    def get_transitive_dependencies(self, entity_id: int) -> Set[int]:
        """Get all entities that are directly or indirectly referenced by the given entity."""
        visited = set()
        to_visit = [entity_id]

        while to_visit:
            current = to_visit.pop()
            if current in visited:
                continue
            visited.add(current)

            entity = self.entities.get(current)
            if entity:
                for ref in entity.references:
                    if ref not in visited and ref in self.entities:
                        to_visit.append(ref)

        return visited

    def get_referencing_entities(self, entity_id: int) -> Set[int]:
        """Get all entities that reference the given entity."""
        return {eid for eid, entity in self.entities.items() if entity_id in entity.references}


class StepWriter:
    """Writer for generating STEP files from selected entities."""

    FILE_SCHEMA = "'AP203_CONFIGURATION_CONTROLLED_3D_DESIGN_OF_MECHANICAL_PARTS_AND_ASSEMBLIES_MIM_LF { 1 0 10303 403 2 1 2 }'"

    def write_step_file(self, output_path: str, part_name: str,
                        entity_ids: Set[int], parser: StepParser) -> None:
        """Write a STEP file with the selected entities."""
        # Sort and renumber entities
        sorted_ids = sorted(entity_ids)
        id_mapping = {old_id: new_id for new_id, old_id in enumerate(sorted_ids, start=1)}

        lines = []
        lines.append("ISO-10303-21;")
        lines.append("HEADER;")
        lines.append("FILE_DESCRIPTION((''),'2;1');")

        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        lines.append(f"FILE_NAME('{part_name.upper()}','{timestamp}',(''),(''),'STEP SPLITTER','STEP SPLITTER','');")

        lines.append("FILE_SCHEMA((")
        lines.append(self.FILE_SCHEMA + "));")
        lines.append("ENDSEC;")
        lines.append("DATA;")

        # Write entities with renumbered IDs
        for old_id in sorted_ids:
            entity = parser.entities.get(old_id)
            if entity:
                line = self._renumber_references(entity.full_line, id_mapping)
                lines.append(line)

        lines.append("ENDSEC;")
        lines.append("END-ISO-10303-21;")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    def _renumber_references(self, line: str, id_mapping: Dict[int, int]) -> str:
        """Renumber all entity references in a line."""
        def replace_ref(match):
            old_id = int(match.group(1))
            new_id = id_mapping.get(old_id)
            if new_id is not None:
                return f"#{new_id}"
            return match.group(0)

        return re.sub(r'#(\d+)', replace_ref, line)


class StepSplitter:
    """Main class for splitting STEP files into individual parts or volumes."""

    def __init__(self):
        self.parser = StepParser()
        self.writer = StepWriter()

    def split(self, input_path: str, output_dir: str) -> None:
        """Analyze and split a STEP file into individual components."""
        print(f"Parsing STEP file: {input_path}")
        self.parser.parse(input_path)

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)

        base_name = self.parser.original_filename

        # Check for assembly (NEXT_ASSEMBLY_USAGE_OCCURRENCE)
        assembly_occurrences = self.parser.find_entities_by_type("NEXT_ASSEMBLY_USAGE_OCCURRENCE")

        if assembly_occurrences:
            print(f"Detected ASSEMBLY with {len(assembly_occurrences)} component references")
            self._split_assembly(output_dir, base_name)
        else:
            # Check for multiple volumes/solids
            solid_bodies = self.parser.find_entities_by_type("MANIFOLD_SOLID_BREP")

            if len(solid_bodies) > 1:
                print(f"Detected PART with {len(solid_bodies)} solid bodies/volumes")
                self._split_multi_volume_part(output_dir, base_name, solid_bodies)
            elif len(solid_bodies) == 1:
                print("Single solid body detected - exporting as single part file")
                self._export_single_part(output_dir, base_name, solid_bodies[0])
            else:
                print("No MANIFOLD_SOLID_BREP entities found")

    def _split_assembly(self, output_dir: str, base_name: str) -> None:
        """Split an assembly into individual parts."""
        product_defs = self.parser.find_entities_by_type("PRODUCT_DEFINITION")
        processed_products = set()
        part_count = 0

        for pd_id in product_defs:
            pd = self.parser.entities.get(pd_id)
            if not pd:
                continue

            # Find SHAPE_DEFINITION_REPRESENTATION entities
            sdr_list = self.parser.find_entities_by_type("SHAPE_DEFINITION_REPRESENTATION")

            for sdr_id in sdr_list:
                sdr = self.parser.entities.get(sdr_id)
                if not sdr:
                    continue

                # Check if this SDR references an ADVANCED_BREP_SHAPE_REPRESENTATION
                for ref in sdr.references:
                    ref_entity = self.parser.entities.get(ref)
                    if ref_entity and ref_entity.type == "ADVANCED_BREP_SHAPE_REPRESENTATION":
                        # Check for solid bodies
                        for shape_ref in ref_entity.references:
                            shape_ref_entity = self.parser.entities.get(shape_ref)
                            if shape_ref_entity and shape_ref_entity.type == "MANIFOLD_SOLID_BREP":
                                product_name = self._extract_product_name(pd)
                                if product_name and product_name not in processed_products:
                                    processed_products.add(product_name)
                                    part_count += 1

                                    # Get all dependencies
                                    dependencies = self._collect_part_dependencies(shape_ref, ref)

                                    output_filename = self._sanitize_filename(product_name) + ".stp"
                                    output_filepath = os.path.join(output_dir, output_filename)

                                    print(f"Extracting part: {product_name}")
                                    self.writer.write_step_file(output_filepath, product_name,
                                                                dependencies, self.parser)
                                    print(f"  -> Saved to: {output_filename}")

        if part_count == 0:
            # Fallback: extract individual solid bodies
            print("Fallback: extracting individual solid bodies...")
            solid_bodies = self.parser.find_entities_by_type("MANIFOLD_SOLID_BREP")
            self._split_multi_volume_part(output_dir, base_name, solid_bodies)
        else:
            print(f"Extracted {part_count} unique parts from assembly")

    def _split_multi_volume_part(self, output_dir: str, base_name: str,
                                  solid_bodies: List[int]) -> None:
        """Split a part with multiple volumes into separate files."""
        for volume_count, solid_id in enumerate(solid_bodies, start=1):
            # Collect all entities needed for this solid body
            dependencies = self._collect_solid_dependencies(solid_id)

            part_name = f"{base_name}_{volume_count}"
            output_filename = f"{part_name}.stp"
            output_filepath = os.path.join(output_dir, output_filename)

            print(f"Extracting volume {volume_count}: {part_name}")
            self.writer.write_step_file(output_filepath, part_name, dependencies, self.parser)
            print(f"  -> Saved to: {output_filename}")

        print(f"Extracted {len(solid_bodies)} volumes from part")

    def _export_single_part(self, output_dir: str, base_name: str, solid_id: int) -> None:
        """Export a single part."""
        dependencies = self._collect_solid_dependencies(solid_id)

        output_filename = f"{base_name}_1.stp"
        output_filepath = os.path.join(output_dir, output_filename)

        print(f"Exporting single part: {base_name}")
        self.writer.write_step_file(output_filepath, base_name, dependencies, self.parser)
        print(f"  -> Saved to: {output_filename}")

    def _collect_solid_dependencies(self, solid_id: int) -> Set[int]:
        """Collect all entities required for a solid body."""
        required = set()

        # Start with the solid body and all its dependencies
        required.update(self.parser.get_transitive_dependencies(solid_id))

        # Add common entities
        self._add_common_entities(required)

        # Add product and shape definition entities
        self._add_product_entities(required, solid_id)

        return required

    def _collect_part_dependencies(self, solid_id: int, shape_rep_id: int) -> Set[int]:
        """Collect all entities required for a part in an assembly."""
        required = set()

        # Get solid body dependencies
        required.update(self.parser.get_transitive_dependencies(solid_id))

        # Get shape representation dependencies
        required.update(self.parser.get_transitive_dependencies(shape_rep_id))

        # Add common entities
        self._add_common_entities(required)

        return required

    def _add_common_entities(self, entities: Set[int]) -> None:
        """Add common entities like colors, units, etc."""
        common_types = {
            'COLOUR_RGB', 'DRAUGHTING_PRE_DEFINED_COLOUR', 'DRAUGHTING_PRE_DEFINED_CURVE_FONT',
            'FILL_AREA_STYLE', 'FILL_AREA_STYLE_COLOUR',
            'SURFACE_STYLE_FILL_AREA', 'SURFACE_SIDE_STYLE', 'SURFACE_STYLE_USAGE',
            'PRESENTATION_STYLE_ASSIGNMENT', 'PRESENTATION_LAYER_ASSIGNMENT',
            'CURVE_STYLE', 'LENGTH_UNIT', 'NAMED_UNIT', 'SI_UNIT',
            'PLANE_ANGLE_UNIT', 'SOLID_ANGLE_UNIT', 'CONVERSION_BASED_UNIT',
            'UNCERTAINTY_MEASURE_WITH_UNIT', 'GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT',
            'GLOBAL_UNIT_ASSIGNED_CONTEXT', 'GEOMETRIC_REPRESENTATION_CONTEXT',
            'REPRESENTATION_CONTEXT', 'PLANE_ANGLE_MEASURE_WITH_UNIT'
        }

        # Find entities that are referenced by our current set
        entities_to_add = set()
        for entity_id in list(entities):
            entity = self.parser.entities.get(entity_id)
            if entity:
                for ref in entity.references:
                    ref_entity = self.parser.entities.get(ref)
                    if ref_entity and (ref_entity.type in common_types or
                                       any(t in ref_entity.type for t in ['UNIT', 'CONTEXT', 'COLOUR'])):
                        entities_to_add.add(ref)
                        entities_to_add.update(self.parser.get_transitive_dependencies(ref))

        entities.update(entities_to_add)

    def _add_product_entities(self, entities: Set[int], solid_id: int) -> None:
        """Add product definition entities for a solid."""
        # Find STYLED_ITEM referencing this solid
        for styled_item_id in self.parser.find_entities_by_type("STYLED_ITEM"):
            styled_item = self.parser.entities.get(styled_item_id)
            if styled_item and solid_id in styled_item.references:
                entities.add(styled_item_id)
                entities.update(self.parser.get_transitive_dependencies(styled_item_id))

        # Find MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION
        for mdgpr_id in self.parser.find_entities_by_type("MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION"):
            mdgpr = self.parser.entities.get(mdgpr_id)
            if mdgpr:
                for ref in mdgpr.references:
                    if ref in entities:
                        entities.update(self.parser.get_transitive_dependencies(mdgpr_id))
                        break

    def _extract_product_name(self, product_def: StepEntity) -> Optional[str]:
        """Extract product name from PRODUCT_DEFINITION."""
        for ref in product_def.references:
            pdf_entity = self.parser.entities.get(ref)
            if pdf_entity and pdf_entity.type == "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE":
                for prod_ref in pdf_entity.references:
                    product = self.parser.entities.get(prod_ref)
                    if product and product.type == "PRODUCT":
                        # Extract name from PRODUCT('name','description',...)
                        match = re.search(r"'([^']+)'", product.content)
                        if match:
                            return match.group(1)
        return None

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        return re.sub(r'[^a-zA-Z0-9_\-]', '_', name)


def main():
    if len(sys.argv) < 2:
        print("STEP File Splitter")
        print("==================")
        print("Splits STEP assembly files into individual part files,")
        print("or multi-volume parts into separate volume files.")
        print()
        print("Usage: python3 step_splitter.py <input.stp> [output_directory]")
        print()
        print("Arguments:")
        print("  input.stp        - Path to the STEP file to split")
        print("  output_directory - Optional: Directory for output files")
        print("                     (defaults to 'RESULT' in input file's directory)")
        print()
        print("Examples:")
        print("  python3 step_splitter.py assembly.stp")
        print("  python3 step_splitter.py part.stp ./output")
        return

    input_path = sys.argv[1]

    if len(sys.argv) >= 3:
        output_dir = sys.argv[2]
    else:
        # Default to RESULT directory in the same location as input file
        parent_dir = os.path.dirname(input_path) or "."
        output_dir = os.path.join(parent_dir, "RESULT")

    try:
        splitter = StepSplitter()
        splitter.split(input_path, output_dir)
        print("\nSplitting completed successfully!")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
