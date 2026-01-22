#!/usr/bin/env python
"""
Sync courses and programs from Bridge LMS into Django database.
Run this script to import all courses and programs from https://safetynow.bridgeapp.com/
"""
import os
import sys
import django
from datetime import datetime

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ohsinsider.settings')
django.setup()

import logging
from django.utils.dateparse import parse_datetime
from lms.models import Course, Program
from lms.bridge_api import BridgeAPI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sync_courses(include_unpublished=False):
    """Sync courses from Bridge to Django."""
    logger.info("Starting course sync from Bridge...")
    logger.info(f"Including unpublished courses: {include_unpublished}")
    
    try:
        bridge_api = BridgeAPI()
        courses = bridge_api.list_courses(limit=None, include_unpublished=include_unpublished)
        logger.info(f"Found {len(courses)} courses in Bridge")
        
        created_count = 0
        updated_count = 0
        
        for course_data in courses:
            bridge_id = course_data.get('id')
            if not bridge_id:
                continue
            
            title = course_data.get('title') or 'Untitled Course'  # Handle None explicitly
            description = course_data.get('description') or ''  # Handle None explicitly
            created_at = parse_datetime(course_data.get('created_at', '')) if course_data.get('created_at') else None
            updated_at = parse_datetime(course_data.get('updated_at', '')) if course_data.get('updated_at') else None
            is_published = course_data.get('is_published', False)
            
            course, created = Course.objects.update_or_create(
                bridge_id=bridge_id,
                defaults={
                    'title': title,
                    'description': description,
                    'created_at': created_at,
                    'updated_at': updated_at,
                    'active': is_published,
                }
            )
            
            if created:
                created_count += 1
                logger.info(f"Created course: {title} (ID: {bridge_id})")
            else:
                updated_count += 1
                logger.debug(f"Updated course: {title} (ID: {bridge_id})")
        
        logger.info(f"Course sync complete: {created_count} created, {updated_count} updated")
        return created_count + updated_count
        
    except Exception as e:
        logger.error(f"Error syncing courses: {str(e)}", exc_info=True)
        raise


def sync_programs(include_unpublished=False):
    """Sync programs from Bridge to Django."""
    logger.info("Starting program sync from Bridge...")
    logger.info(f"Including unpublished programs: {include_unpublished}")
    
    try:
        bridge_api = BridgeAPI()
        programs = bridge_api.list_programs(limit=None, include_unpublished=include_unpublished)
        logger.info(f"Found {len(programs)} programs in Bridge")
        
        created_count = 0
        updated_count = 0
        
        for program_data in programs:
            bridge_id = program_data.get('id')
            if not bridge_id:
                continue
            
            title = program_data.get('title') or 'Untitled Program'  # Handle None explicitly
            description = program_data.get('description') or ''  # Handle None explicitly
            created_at = parse_datetime(program_data.get('created_at', '')) if program_data.get('created_at') else None
            updated_at = parse_datetime(program_data.get('updated_at', '')) if program_data.get('updated_at') else None
            is_published = program_data.get('is_published', False)
            
            program, created = Program.objects.update_or_create(
                bridge_id=bridge_id,
                defaults={
                    'title': title,
                    'description': description,
                    'created_at': created_at,
                    'updated_at': updated_at,
                    'active': is_published,
                }
            )
            
            if created:
                created_count += 1
                logger.info(f"Created program: {title} (ID: {bridge_id})")
            else:
                updated_count += 1
                logger.debug(f"Updated program: {title} (ID: {bridge_id})")
        
        logger.info(f"Program sync complete: {created_count} created, {updated_count} updated")
        return created_count + updated_count
        
    except Exception as e:
        logger.error(f"Error syncing programs: {str(e)}", exc_info=True)
        raise


def main():
    """Main sync function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync courses and programs from Bridge')
    parser.add_argument('--include-unpublished', action='store_true',
                       help='Include unpublished/archived courses and programs (default: only published)')
    
    args = parser.parse_args()
    
    include_unpublished = args.include_unpublished
    
    logger.info("=" * 80)
    logger.info("Bridge Course & Program Sync")
    logger.info(f"Including unpublished: {include_unpublished}")
    logger.info("=" * 80)
    
    try:
        courses_synced = sync_courses(include_unpublished=include_unpublished)
        programs_synced = sync_programs(include_unpublished=include_unpublished)
        
        logger.info("=" * 80)
        logger.info(f"Sync complete: {courses_synced} courses, {programs_synced} programs")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"Sync failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

