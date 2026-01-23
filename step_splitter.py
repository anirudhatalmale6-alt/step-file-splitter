#!/usr/bin/env python3
"""
STEP File Splitter
==================
Splits STEP (ISO 10303-21) assembly files into individual part files,
or multi-volume parts into separate volume files.

Features:
- Detects and merges duplicate parts (creates one file with count)
- Generates report file listing all parts and their counts
- Supports both assemblies and multi-volume parts

Usage:
    python3 step_splitter.py <input.stp> [output_directory]

Author: Anirudha
"""

import re
import os
import sys
import hashlib
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
        match = re.match(r'#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*)\)\s*;', line, re.DOTALL)
        if match:
            entity_id = int(match.group(1))
            entity_type = match.group(2)
            content = match.group(3)
            self.entities[entity_id] = StepEntity(entity_id, entity_type, content, line)
        else:
            match = re.match(r'#(\d+)\s*=\s*\((.*)\)\s*;', line, re.DOTALL)
            if match:
                entity_id = int(match.group(1))
                content = match.group(2)
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


class GeometryHasher:
    """Computes geometry hashes for duplicate detection."""

    def __init__(self, parser: StepParser):
        self.parser = parser

    def compute_geometry_hash(self, solid_id: int) -> str:
        """
        Compute a hash of the geometry for duplicate detection.
        This normalizes the geometry by removing entity IDs and comparing structure.
        """
        # Get all geometric entities for this solid
        deps = self.parser.get_transitive_dependencies(solid_id)

        # Filter to only geometric entities (not colors, styles, etc.)
        geometric_types = {
            'CARTESIAN_POINT', 'DIRECTION', 'VECTOR', 'LINE', 'CIRCLE', 'ELLIPSE',
            'B_SPLINE_CURVE', 'B_SPLINE_SURFACE', 'PLANE', 'CYLINDRICAL_SURFACE',
            'CONICAL_SURFACE', 'SPHERICAL_SURFACE', 'TOROIDAL_SURFACE',
            'AXIS2_PLACEMENT_3D', 'AXIS1_PLACEMENT', 'VERTEX_POINT', 'EDGE_CURVE',
            'ORIENTED_EDGE', 'EDGE_LOOP', 'FACE_OUTER_BOUND', 'FACE_BOUND',
            'ADVANCED_FACE', 'CLOSED_SHELL', 'OPEN_SHELL', 'MANIFOLD_SOLID_BREP'
        }

        # Collect geometric content (normalized - without entity IDs)
        geo_content = []
        for eid in sorted(deps):
            entity = self.parser.entities.get(eid)
            if entity and entity.type in geometric_types:
                # Normalize: remove entity ID, keep type and numeric values
                normalized = self._normalize_entity(entity)
                geo_content.append(normalized)

        # Sort for consistency
        geo_content.sort()

        # Compute hash
        content_str = '\n'.join(geo_content)
        return hashlib.md5(content_str.encode()).hexdigest()

    def _normalize_entity(self, entity: StepEntity) -> str:
        """Normalize an entity for comparison (remove IDs, keep structure)."""
        # Extract numeric values from the content
        content = entity.content

        # Remove all entity references (#xxx) - we only care about the numeric geometry
        normalized = re.sub(r'#\d+', '#REF', content)

        # Round floating point numbers to reduce precision issues
        def round_number(match):
            try:
                num = float(match.group(0))
                return f"{num:.6g}"
            except:
                return match.group(0)

        normalized = re.sub(r'-?\d+\.?\d*E?[+-]?\d*', round_number, normalized)

        return f"{entity.type}({normalized})"


class StepSplitter:
    """Main class for splitting STEP files into individual parts or volumes."""

    def __init__(self):
        self.parser = StepParser()
        self.writer = StepWriter()
        self.hasher = None
        self.part_report = []  # List of (name, count) tuples

    def split(self, input_path: str, output_dir: str) -> None:
        """Analyze and split a STEP file into individual components."""
        print(f"Parsing STEP file: {input_path}")
        self.parser.parse(input_path)
        self.hasher = GeometryHasher(self.parser)
        self.part_report = []

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

        # Write report file
        self._write_report(output_dir, base_name)

    def _split_assembly(self, output_dir: str, base_name: str) -> None:
        """Split an assembly into individual parts with duplicate detection."""
        # Count part occurrences from NEXT_ASSEMBLY_USAGE_OCCURRENCE
        nauo_list = self.parser.find_entities_by_type("NEXT_ASSEMBLY_USAGE_OCCURRENCE")

        # Map product definitions to their occurrence counts
        part_occurrence_count: Dict[int, int] = {}  # product_definition_id -> count

        for nauo_id in nauo_list:
            nauo = self.parser.entities.get(nauo_id)
            if nauo:
                # NAUO references PRODUCT_DEFINITION entities
                for ref in nauo.references:
                    ref_entity = self.parser.entities.get(ref)
                    if ref_entity and ref_entity.type == "PRODUCT_DEFINITION":
                        part_occurrence_count[ref] = part_occurrence_count.get(ref, 0) + 1

        # Find all MANIFOLD_SOLID_BREP entities and their product names
        solid_bodies = self.parser.find_entities_by_type("MANIFOLD_SOLID_BREP")

        # Map each solid to its product name and count
        solid_info: Dict[int, Tuple[str, int]] = {}  # solid_id -> (product_name, count)

        for solid_id in solid_bodies:
            product_name = self._find_product_for_solid(solid_id)
            pd_id = self._find_product_definition_for_solid(solid_id)

            if product_name:
                # Get occurrence count from NAUO analysis
                count = part_occurrence_count.get(pd_id, 1) if pd_id else 1
                solid_info[solid_id] = (product_name, count)
            else:
                solid_info[solid_id] = (f"{base_name}-{solid_id}", 1)

        # Compute geometry hashes for duplicate detection (for geometrically identical parts)
        print("Computing geometry hashes for duplicate detection...")
        hash_to_solids: Dict[str, List[Tuple[int, str, int]]] = {}

        for solid_id, (product_name, count) in solid_info.items():
            geo_hash = self.hasher.compute_geometry_hash(solid_id)
            if geo_hash not in hash_to_solids:
                hash_to_solids[geo_hash] = []
            hash_to_solids[geo_hash].append((solid_id, product_name, count))

        # Export unique parts
        unique_count = 0
        total_instances = 0

        for geo_hash, solids_list in hash_to_solids.items():
            # Sum counts for geometrically identical parts
            total_count = sum(item[2] for item in solids_list)
            total_instances += total_count

            # Use the first solid and its name
            solid_id, product_name, _ = solids_list[0]
            unique_count += 1

            # Collect dependencies
            dependencies = self._collect_solid_dependencies(solid_id)

            # Generate filename
            output_filename = self._sanitize_filename(product_name) + ".stp"
            output_filepath = os.path.join(output_dir, output_filename)

            if total_count > 1:
                print(f"Extracting part: {product_name} (x{total_count} instances)")
            else:
                print(f"Extracting part: {product_name}")

            self.writer.write_step_file(output_filepath, product_name, dependencies, self.parser)
            print(f"  -> Saved to: {output_filename}")

            # Add to report
            self.part_report.append((product_name, total_count))

        print(f"\nExtracted {unique_count} unique parts from {total_instances} total instances")

    def _split_multi_volume_part(self, output_dir: str, base_name: str,
                                  solid_bodies: List[int]) -> None:
        """Split a part with multiple volumes with duplicate detection."""
        # Compute geometry hashes for duplicate detection
        print("Computing geometry hashes for duplicate detection...")
        hash_to_solids: Dict[str, List[int]] = {}

        for solid_id in solid_bodies:
            geo_hash = self.hasher.compute_geometry_hash(solid_id)
            if geo_hash not in hash_to_solids:
                hash_to_solids[geo_hash] = []
            hash_to_solids[geo_hash].append(solid_id)

        # Export unique volumes
        unique_count = 0
        total_instances = len(solid_bodies)
        used_names: Dict[str, int] = {}  # Track name usage for deduplication

        for geo_hash, solids_list in hash_to_solids.items():
            count = len(solids_list)
            unique_count += 1

            # Use the first solid
            solid_id = solids_list[0]

            # Collect dependencies
            dependencies = self._collect_solid_dependencies(solid_id)

            # Try to get part name from the solid body entity itself
            part_name = self._get_solid_name(solid_id)
            if not part_name:
                # Fallback to product name lookup
                part_name = self._find_product_for_solid(solid_id)
            if not part_name:
                # Final fallback: use base_name with counter
                part_name = f"{base_name}_{unique_count}"

            # Handle duplicate names by adding entity ID suffix
            sanitized = self._sanitize_filename(part_name)
            if sanitized in used_names:
                used_names[sanitized] += 1
                part_name = f"{part_name}-{solid_id}"
                sanitized = self._sanitize_filename(part_name)
            else:
                used_names[sanitized] = 1

            output_filename = f"{sanitized}.stp"
            output_filepath = os.path.join(output_dir, output_filename)

            if count > 1:
                print(f"Extracting volume {unique_count}: {part_name} (x{count} identical instances)")
            else:
                print(f"Extracting volume {unique_count}: {part_name}")

            self.writer.write_step_file(output_filepath, part_name, dependencies, self.parser)
            print(f"  -> Saved to: {output_filename}")

            # Add to report
            self.part_report.append((part_name, count))

        print(f"\nExtracted {unique_count} unique volumes from {total_instances} total instances")

    def _export_single_part(self, output_dir: str, base_name: str, solid_id: int) -> None:
        """Export a single part."""
        dependencies = self._collect_solid_dependencies(solid_id)

        # Try to get part name from the solid body entity itself
        part_name = self._get_solid_name(solid_id)
        if not part_name:
            # Fallback to product name lookup
            part_name = self._find_product_for_solid(solid_id)
        if not part_name:
            # Final fallback: use base_name with counter
            part_name = f"{base_name}_1"

        output_filename = f"{self._sanitize_filename(part_name)}.stp"
        output_filepath = os.path.join(output_dir, output_filename)

        print(f"Exporting single part: {part_name}")
        self.writer.write_step_file(output_filepath, part_name, dependencies, self.parser)
        print(f"  -> Saved to: {output_filename}")

        self.part_report.append((part_name, 1))

    def _get_solid_name(self, solid_id: int) -> Optional[str]:
        """Extract the name directly from a MANIFOLD_SOLID_BREP entity."""
        entity = self.parser.entities.get(solid_id)
        if entity and entity.type == "MANIFOLD_SOLID_BREP":
            # MANIFOLD_SOLID_BREP('name',#shell_ref)
            # Extract the first quoted string (the name)
            match = re.search(r"'([^']*)'", entity.content)
            if match:
                name = match.group(1).strip()
                if name:  # Only return if name is not empty
                    return name
        return None

    def _find_product_for_solid(self, solid_id: int) -> Optional[str]:
        """Find the product name associated with a solid body."""
        pd = self._find_product_definition_entity_for_solid(solid_id)
        if pd:
            return self._extract_product_name(pd)
        return None

    def _find_product_definition_for_solid(self, solid_id: int) -> Optional[int]:
        """Find the PRODUCT_DEFINITION entity ID for a solid body."""
        pd = self._find_product_definition_entity_for_solid(solid_id)
        return pd.id if pd else None

    def _find_product_definition_entity_for_solid(self, solid_id: int) -> Optional[StepEntity]:
        """Find the PRODUCT_DEFINITION entity associated with a solid body."""
        # Find ADVANCED_BREP_SHAPE_REPRESENTATION containing this solid
        for abrep_id in self.parser.find_entities_by_type("ADVANCED_BREP_SHAPE_REPRESENTATION"):
            abrep = self.parser.entities.get(abrep_id)
            if abrep and solid_id in abrep.references:
                # Method 1: Direct - Find SHAPE_DEFINITION_REPRESENTATION referencing this ABREP
                for sdr_id in self.parser.find_entities_by_type("SHAPE_DEFINITION_REPRESENTATION"):
                    sdr = self.parser.entities.get(sdr_id)
                    if sdr and abrep_id in sdr.references:
                        pd = self._get_product_definition_from_sdr(sdr)
                        if pd:
                            return pd

                # Method 2: Via SHAPE_REPRESENTATION_RELATIONSHIP
                # Some STEP files link ADVANCED_BREP_SHAPE_REPRESENTATION to SHAPE_REPRESENTATION
                # via SHAPE_REPRESENTATION_RELATIONSHIP, then SDR references the SHAPE_REPRESENTATION
                for srr_id in self.parser.find_entities_by_type("SHAPE_REPRESENTATION_RELATIONSHIP"):
                    srr = self.parser.entities.get(srr_id)
                    if srr and abrep_id in srr.references:
                        # Find the SHAPE_REPRESENTATION also referenced by this relationship
                        for shape_rep_id in srr.references:
                            if shape_rep_id == abrep_id:
                                continue
                            shape_rep = self.parser.entities.get(shape_rep_id)
                            if shape_rep and shape_rep.type == "SHAPE_REPRESENTATION":
                                # Find SDR referencing this SHAPE_REPRESENTATION
                                for sdr_id in self.parser.find_entities_by_type("SHAPE_DEFINITION_REPRESENTATION"):
                                    sdr = self.parser.entities.get(sdr_id)
                                    if sdr and shape_rep_id in sdr.references:
                                        pd = self._get_product_definition_from_sdr(sdr)
                                        if pd:
                                            return pd
        return None

    def _get_product_definition_from_sdr(self, sdr: StepEntity) -> Optional[StepEntity]:
        """Extract PRODUCT_DEFINITION from a SHAPE_DEFINITION_REPRESENTATION."""
        # Find PRODUCT_DEFINITION_SHAPE referenced by SDR
        for ref in sdr.references:
            pds = self.parser.entities.get(ref)
            if pds and pds.type == "PRODUCT_DEFINITION_SHAPE":
                # Find PRODUCT_DEFINITION referenced by PDS
                for pds_ref in pds.references:
                    pd = self.parser.entities.get(pds_ref)
                    if pd and pd.type == "PRODUCT_DEFINITION":
                        return pd
        return None

    def _collect_solid_dependencies(self, solid_id: int) -> Set[int]:
        """Collect all entities required for a solid body, including product structure."""
        required = set()
        # Get pure geometry dependencies (downward from solid)
        required.update(self.parser.get_transitive_dependencies(solid_id))

        # Add ADVANCED_BREP_SHAPE_REPRESENTATION that contains this solid
        # This provides the geometric context and units needed by OpenCASCADE
        abrep_id_found = None
        for abrep_id in self.parser.find_entities_by_type("ADVANCED_BREP_SHAPE_REPRESENTATION"):
            abrep = self.parser.entities.get(abrep_id)
            if abrep and solid_id in abrep.references:
                abrep_id_found = abrep_id
                required.add(abrep_id)
                # Add the context/units referenced by ABREP
                for ref in abrep.references:
                    if ref != solid_id:
                        required.add(ref)
                        required.update(self.parser.get_transitive_dependencies(ref))
                break

        # Add product structure entities (PRODUCT_DEFINITION, PRODUCT, etc.)
        self._add_product_structure(required, solid_id, abrep_id_found)

        # Add styling for this specific solid only
        self._add_styled_items_for_solid(required, solid_id)

        return required

    def _add_product_structure(self, entities: Set[int], solid_id: int,
                                abrep_id: Optional[int]) -> None:
        """Add PRODUCT_DEFINITION and related entities for a solid body.

        This creates the product wrapper that OpenCASCADE requires:
        APPLICATION_CONTEXT -> PRODUCT_DEFINITION_CONTEXT -> PRODUCT_DEFINITION
        -> PRODUCT_DEFINITION_FORMATION -> PRODUCT
        -> PRODUCT_DEFINITION_SHAPE -> SHAPE_DEFINITION_REPRESENTATION
        """
        if not abrep_id:
            return

        # Find SHAPE_REPRESENTATION linked to this ABREP
        # Method 1: Direct SDR referencing ABREP
        for sdr_id in self.parser.find_entities_by_type("SHAPE_DEFINITION_REPRESENTATION"):
            sdr = self.parser.entities.get(sdr_id)
            if sdr and abrep_id in sdr.references:
                entities.add(sdr_id)
                self._add_sdr_chain(entities, sdr)
                return

        # Method 2: Via SHAPE_REPRESENTATION_RELATIONSHIP
        for srr_id in self.parser.find_entities_by_type("SHAPE_REPRESENTATION_RELATIONSHIP"):
            srr = self.parser.entities.get(srr_id)
            if srr and abrep_id in srr.references:
                entities.add(srr_id)
                # Find SHAPE_REPRESENTATION linked by this relationship
                for shape_rep_id in srr.references:
                    if shape_rep_id == abrep_id:
                        continue
                    shape_rep = self.parser.entities.get(shape_rep_id)
                    if shape_rep and shape_rep.type == "SHAPE_REPRESENTATION":
                        entities.add(shape_rep_id)
                        entities.update(self.parser.get_transitive_dependencies(shape_rep_id))
                        # Find SDR referencing this SHAPE_REPRESENTATION
                        for sdr_id in self.parser.find_entities_by_type("SHAPE_DEFINITION_REPRESENTATION"):
                            sdr = self.parser.entities.get(sdr_id)
                            if sdr and shape_rep_id in sdr.references:
                                entities.add(sdr_id)
                                self._add_sdr_chain(entities, sdr)
                                return

    def _add_sdr_chain(self, entities: Set[int], sdr: StepEntity) -> None:
        """Add the full product chain from a SHAPE_DEFINITION_REPRESENTATION."""
        for ref in sdr.references:
            pds = self.parser.entities.get(ref)
            if pds and pds.type == "PRODUCT_DEFINITION_SHAPE":
                entities.add(pds.id)
                # Get PRODUCT_DEFINITION
                for pds_ref in pds.references:
                    pd = self.parser.entities.get(pds_ref)
                    if pd and pd.type == "PRODUCT_DEFINITION":
                        entities.add(pd.id)
                        # Add all transitive deps of PRODUCT_DEFINITION
                        # (PRODUCT_DEFINITION_FORMATION, PRODUCT, PRODUCT_CONTEXT,
                        #  APPLICATION_CONTEXT, APPLICATION_PROTOCOL_DEFINITION, etc.)
                        entities.update(self.parser.get_transitive_dependencies(pd.id))

                        # Also find PROPERTY_DEFINITION entities referencing this PD
                        for prop_id in self.parser.find_entities_by_type("PROPERTY_DEFINITION"):
                            prop = self.parser.entities.get(prop_id)
                            if prop and pd.id in prop.references:
                                entities.add(prop_id)
                                entities.update(self.parser.get_transitive_dependencies(prop_id))
                                # Find PROPERTY_DEFINITION_REPRESENTATION
                                for pdr_id in self.parser.find_entities_by_type("PROPERTY_DEFINITION_REPRESENTATION"):
                                    pdr = self.parser.entities.get(pdr_id)
                                    if pdr and prop_id in pdr.references:
                                        entities.add(pdr_id)
                                        entities.update(self.parser.get_transitive_dependencies(pdr_id))

    def _add_styled_items_for_solid(self, entities: Set[int], solid_id: int) -> None:
        """Add STYLED_ITEM and its styling dependencies for a specific solid only."""
        for styled_item_id in self.parser.find_entities_by_type("STYLED_ITEM"):
            styled_item = self.parser.entities.get(styled_item_id)
            if styled_item and solid_id in styled_item.references:
                # Add the styled item itself
                entities.add(styled_item_id)
                # Add only the styling chain (not the geometry which is already included)
                for ref in styled_item.references:
                    if ref != solid_id:
                        entities.add(ref)
                        entities.update(self.parser.get_transitive_dependencies(ref))

    def _extract_product_name(self, product_def: StepEntity) -> Optional[str]:
        """Extract product name from PRODUCT_DEFINITION."""
        for ref in product_def.references:
            pdf_entity = self.parser.entities.get(ref)
            if pdf_entity and pdf_entity.type == "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE":
                for prod_ref in pdf_entity.references:
                    product = self.parser.entities.get(prod_ref)
                    if product and product.type == "PRODUCT":
                        match = re.search(r"'([^']+)'", product.content)
                        if match:
                            return match.group(1)
        return None

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        return re.sub(r'[^a-zA-Z0-9_\-]', '_', name)

    def _write_report(self, output_dir: str, base_name: str) -> None:
        """Write a report file listing all parts and their counts."""
        report_filename = f"{base_name}.txt"
        # Report file goes inside the SPLIT folder
        report_filepath = os.path.join(output_dir, report_filename)

        # Sort by part name
        sorted_report = sorted(self.part_report, key=lambda x: x[0])

        lines = []
        for part_name, count in sorted_report:
            lines.append(f"{part_name};{count}")

        with open(report_filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        print(f"\nReport saved to: {report_filename}")


def main():
    if len(sys.argv) < 2:
        print("STEP File Splitter")
        print("==================")
        print("Splits STEP assembly files into individual part files,")
        print("or multi-volume parts into separate volume files.")
        print()
        print("Features:")
        print("- Detects and merges duplicate parts (creates one file with count)")
        print("- Generates report file listing all parts and their counts")
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
        print()
        print("Output:")
        print("  - Individual .stp files for each unique part/volume")
        print("  - A .txt report file with part names and counts")
        print("    (e.g., 'PART_NAME;4' means 4 identical copies)")
        return

    input_path = sys.argv[1]
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    if len(sys.argv) >= 3:
        output_dir = sys.argv[2]
    else:
        parent_dir = os.path.dirname(input_path) or "."
        output_dir = os.path.join(parent_dir, f"SPLIT-{base_name}")

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
