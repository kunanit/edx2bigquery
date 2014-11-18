#!/usr/bin/python
#
# common procedures to process all tracking logs, and update table based on new tracking logs

import sys
import datetime
import bqutil

def run_query_on_tracking_logs(SQL, table, course_id, force_recompute=False, use_dataset_latest=False, 
                               end_date=None, 
                               get_date_function=None,
                               existing=None,
                               log_dates=None):
    '''
    make a certain table (with SQL given) for specified course_id.

    The master table holds all the data for a course.  It isn't split into separate
    days.  It is ordered in time, however.  To update it, a new day's logs
    are processed, then the results appended to this table.

    If the table doesn't exist, then run it once on all
    the existing tracking logs.  

    If it already exists, then run a query on it to see what dates have
    already been done.  Then do all tracking logs except those which
    have already been done.  Append the results to the existing table.

    If the query fails because of "Resources exceeded during query execution"
    then try setting the end_date, to do part at a time.

    NOTE: the SQL must produce a result which is ordered by date, in increaseing order.
    '''

    dataset = bqutil.course_id2dataset(course_id, use_dataset_latest=use_dataset_latest)
    log_dataset = bqutil.course_id2dataset(course_id, dtype="logs")

    if existing is None:
        existing = bqutil.get_list_of_table_ids(dataset)

    if log_dates is None:
        log_tables = [x for x in bqutil.get_list_of_table_ids(log_dataset) if x.startswith('tracklog_20')]
        log_dates = [x[9:] for x in log_tables]

    min_date = min(log_dates)
    max_date = max(log_dates)

    if end_date is not None:
        print "[run_query_on_tracking_logs] %s: Using end_date=%s for max_date cutoff" % (table, end_date)
        max_date = end_date.replace('-','')	# end_date should be YYYY-MM-DD

    if force_recompute:
        overwrite = True
    else:
        overwrite = False

    if (not overwrite) and table in existing:
        # find out what the end date is of the current table
        pc_last = bqutil.get_table_data(dataset, table, startIndex=-10, maxResults=100)
        last_dates = [get_date_function(x) for x in pc_last['data']]
        table_max_date = max(last_dates).strftime('%Y%m%d')
        if max_date <= table_max_date:
            print '--> %s already exists, max_date=%s, but tracking log data min=%s, max=%s, nothing new!' % (table, 
                                                                                                              table_max_date,
                                                                                                              min_date,
                                                                                                              max_date)
            return
        min_date = (max(last_dates) + datetime.timedelta(days=1)).strftime('%Y%m%d')
        print '--> %s already exists, max_date=%s, adding tracking log data from %s to max=%s' % (table, 
                                                                                                  table_max_date,
                                                                                                  min_date,
                                                                                                  max_date)
        overwrite = 'append'

    from_datasets = """(
                  TABLE_QUERY({dataset},
                       "integer(regexp_extract(table_id, r'tracklog_([0-9]+)')) BETWEEN {start} and {end}"
                     )
                  )
         """.format(dataset=log_dataset, start=min_date, end=max_date)

    the_sql = SQL.format(course_id=course_id, DATASETS=from_datasets)

    if overwrite=='append':
        print "Appending to %s table for course %s (start=%s, end=%s) [%s]"  % (table, course_id, min_date, max_date, datetime.datetime.now())
    else:
        print "Making new %s table for course %s (start=%s, end=%s) [%s]"  % (table, course_id, min_date, max_date, datetime.datetime.now())
    sys.stdout.flush()

    try:
        bqutil.create_bq_table(dataset, table, the_sql, wait=True, overwrite=overwrite)
    except Exception as err:
        if 'Resources exceeded during query execution' in str(err):
            def get_ym(x):
                return int(x[0:4]), int(x[4:6]), int(x[6:])
            (min_year, min_month, min_day) = get_ym(min_date)
            (max_year, max_month, max_day) = get_ym(max_date)
            nmonths = max_month - min_month + 12 * (max_year - min_year)
            print "====> ERROR with resources exceeded during query execution; re-trying based on one month's data at a time"
            (end_year, end_month) = (min_year, min_month)
            for dm in range(nmonths):
                end_month += 1
                if end_month > 12:
                    end_month = 1
                    end_year += 1
                end_date = "%04d-%02d-%02d" % (end_year, end_month, min_day)
                print "--> with end_date=%s" % end_date
                sys.stdout.flush()
                run_query_on_tracking_logs(SQL, table, course_id, force_recompute=force_recompute, 
                                           use_dataset_latest=use_dataset_latest,
                                           end_date=end_date, 
                                           get_date_function=get_date_function,
                                           existing=existing,
                                           log_dates=log_dates)
                force_recompute = False		# after first, don't force recompute
            return
        else:
            raise

    if overwrite=='append':
        txt = '[%s] added tracking log data from %s to %s' % (datetime.datetime.now(), min_date, max_date)
        bqutil.add_description_to_table(dataset, table, txt, append=True)
    
    print "Done with course %s (end %s)"  % (course_id, datetime.datetime.now())
    print "="*77
    sys.stdout.flush()
    