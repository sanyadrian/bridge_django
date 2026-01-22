#!/usr/bin/env python
"""
Add courses from CSV file to a package.
Matches courses by title and adds them to the specified package.
"""
import os
import sys
import django
import csv
from difflib import SequenceMatcher

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ohsinsider.settings')
django.setup()

import logging
from lms.models import Course, Package

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def similarity(a, b):
    """Calculate similarity ratio between two strings."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_course_by_title(title, threshold=0.85):
    """
    Find a course by title, with fuzzy matching.
    
    Args:
        title: Course title to search for
        threshold: Minimum similarity ratio (0-1)
    
    Returns:
        Course object or None
    """
    # First try exact match (case-insensitive)
    try:
        course = Course.objects.get(title__iexact=title.strip())
        return course, 1.0
    except Course.DoesNotExist:
        pass
    except Course.MultipleObjectsReturned:
        # If multiple exact matches, return the first one
        course = Course.objects.filter(title__iexact=title.strip()).first()
        if course:
            return course, 1.0
    
    # Try fuzzy matching
    best_match = None
    best_ratio = 0.0
    
    for course in Course.objects.all():
        if course.title:
            ratio = similarity(title, course.title)
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = course
    
    if best_ratio >= threshold:
        return best_match, best_ratio
    
    return None, best_ratio


def add_courses_to_package(csv_file_path, package_name, prefix='ohsi', create_package=False):
    """
    Read courses from CSV and add them to a package.
    
    Args:
        csv_file_path: Path to CSV file with course titles
        package_name: Name of the package
        prefix: Package prefix (ohsi/ilt/hri)
        create_package: If True, create package if it doesn't exist
    """
    logger.info("=" * 80)
    logger.info(f"Adding courses to package: {package_name}")
    logger.info("=" * 80)
    
    # Get or create package
    try:
        package = Package.objects.get(name=package_name)
        logger.info(f"Found existing package: {package_name}")
    except Package.DoesNotExist:
        if create_package:
            package = Package.objects.create(
                name=package_name,
                prefix=prefix,
                description=f"Package created from CSV: {package_name}",
                active=True
            )
            logger.info(f"Created new package: {package_name}")
        else:
            logger.error(f"Package '{package_name}' not found. Use create_package=True to create it.")
            return
    
    # Read CSV file
    courses_found = []
    courses_not_found = []
    courses_already_in_package = []
    courses_added = []
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                course_title = row.get('Course Title', '').strip()
                if not course_title:
                    continue
                
                logger.debug(f"Looking for course: {course_title}")
                
                # Find course
                course, similarity_ratio = find_course_by_title(course_title)
                
                if course:
                    # Check if already in package
                    if package.courses.filter(id=course.id).exists():
                        courses_already_in_package.append({
                            'csv_title': course_title,
                            'db_title': course.title,
                            'bridge_id': course.bridge_id,
                            'similarity': similarity_ratio
                        })
                        logger.debug(f"  ✓ Already in package: {course.title} (ID: {course.bridge_id})")
                    else:
                        # Add to package
                        package.courses.add(course)
                        courses_added.append({
                            'csv_title': course_title,
                            'db_title': course.title,
                            'bridge_id': course.bridge_id,
                            'similarity': similarity_ratio
                        })
                        logger.info(f"  ✓ Added: {course.title} (ID: {course.bridge_id}, similarity: {similarity_ratio:.2%})")
                    
                    courses_found.append({
                        'csv_title': course_title,
                        'db_title': course.title,
                        'bridge_id': course.bridge_id,
                        'similarity': similarity_ratio
                    })
                else:
                    courses_not_found.append({
                        'csv_title': course_title,
                        'best_similarity': similarity_ratio
                    })
                    logger.warning(f"  ✗ Not found: {course_title} (best similarity: {similarity_ratio:.2%})")
    
    except FileNotFoundError:
        logger.error(f"CSV file not found: {csv_file_path}")
        return
    except Exception as e:
        logger.error(f"Error reading CSV file: {str(e)}", exc_info=True)
        return
    
    # Summary
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total courses in CSV: {len(courses_found) + len(courses_not_found)}")
    logger.info(f"Courses found: {len(courses_found)}")
    logger.info(f"  - Newly added: {len(courses_added)}")
    logger.info(f"  - Already in package: {len(courses_already_in_package)}")
    logger.info(f"Courses not found: {len(courses_not_found)}")
    logger.info(f"Total courses in package now: {package.courses.count()}")
    
    # Show not found courses
    if courses_not_found:
        logger.info("\nCourses NOT FOUND (check spelling or sync from Bridge):")
        for item in courses_not_found[:20]:  # Show first 20
            logger.info(f"  - {item['csv_title']} (best match: {item['best_similarity']:.2%})")
        if len(courses_not_found) > 20:
            logger.info(f"  ... and {len(courses_not_found) - 20} more")
    
    # Show low similarity matches
    low_similarity = [c for c in courses_found if c['similarity'] < 0.95]
    if low_similarity:
        logger.info("\nCourses with LOW SIMILARITY (may need manual check):")
        for item in low_similarity[:10]:  # Show first 10
            logger.info(f"  CSV: {item['csv_title']}")
            logger.info(f"  DB:  {item['db_title']} (similarity: {item['similarity']:.2%})")
    
    logger.info("=" * 80)


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Add courses from CSV to a package')
    parser.add_argument('csv_file', help='Path to CSV file with course titles')
    parser.add_argument('package_name', help='Name of the package')
    parser.add_argument('--prefix', default='ohsi', choices=['ohsi', 'ilt', 'hri'],
                       help='Package prefix (default: ohsi)')
    parser.add_argument('--create', action='store_true',
                       help='Create package if it does not exist')
    
    args = parser.parse_args()
    
    add_courses_to_package(
        csv_file_path=args.csv_file,
        package_name=args.package_name,
        prefix=args.prefix,
        create_package=args.create
    )


if __name__ == '__main__':
    main()

