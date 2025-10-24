# Backend scheduler service

import os
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from integraldb.backend.ingestion import email_ingest, drive_ingest
from integraldb.backend.processing import extract, embed
from integraldb.backend.config import config
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(config.DATA_DIR, 'backend.log'))
    ]
)

logger = logging.getLogger(__name__)

def update_database():
    """Run the complete ingestion and processing pipeline"""
    try:
        # Run email ingestion
        logger.info("Starting email ingestion...")
        email_service = email_ingest.get_gmail_service()
        if email_service:
            email_data = email_ingest.fetch_latest_emails(email_service)
            email_ingest.save_to_csv(email_data)
            logger.info(f"Processed {len(email_data)} emails")

        # Run drive ingestion
        logger.info("Starting drive ingestion...")
        drive_service = drive_ingest.get_drive_service()
        if drive_service:
            drive_ingest.fetch_drive_files(drive_service)
            logger.info("Drive ingestion completed")

        # Run processing
        logger.info("Starting data extraction...")
        extract.main()  # Process structured data
        
        logger.info("Starting embedding generation...")
        embed.main()    # Process embeddings
        
        logger.info("Database update cycle completed successfully")
        
    except Exception as e:
        logger.error(f"Error in update cycle: {e}", exc_info=True)

def main():
    """Main entry point for the backend service"""
    try:
        logger.info("Starting IntegralDB backend service...")
        
        # Create scheduler
        scheduler = BlockingScheduler()
        
        # Add the update job
        scheduler.add_job(
            update_database,
            trigger=IntervalTrigger(seconds=config.UPDATE_INTERVAL),
            id='update_database',
            name='Update Database',
            replace_existing=True
        )
        
        # Run initial update
        logger.info("Running initial database update...")
        update_database()
        
        # Start the scheduler
        logger.info(f"Starting scheduler (update interval: {config.UPDATE_INTERVAL}s)")
        scheduler.start()
        
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down backend service...")
    except Exception as e:
        logger.error(f"Fatal error in backend service: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()