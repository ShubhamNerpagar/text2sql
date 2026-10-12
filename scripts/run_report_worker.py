#!/usr/bin/env python3
from app.services.report_service import ReportService

if __name__ == '__main__':
    result=ReportService().run_due()
    print(f"report worker: {result['due_count']} due report(s)")
    for run in result['runs']:
        print(run)
