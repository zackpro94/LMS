"""
Export utilities for generating PDF and Excel reports with dual Gregorian & Ethiopian Calendar support.
"""
from datetime import datetime
from io import BytesIO

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from django.http import HttpResponse
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

from .ethiopian_calendar import format_ethiopian_date


def export_letters_to_excel(letters, title="Letters Report"):
    """
    Export letters to Excel format using openpyxl with dual Gregorian and Ethiopian dates.
    """
    output = BytesIO()
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Letters"

    # Define styles
    header_font = Font(bold=True, color="FFFFFF", size=10)
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    border = Border(
        left=Side(style='thin', color='D0D0D0'),
        right=Side(style='thin', color='D0D0D0'),
        top=Side(style='thin', color='D0D0D0'),
        bottom=Side(style='thin', color='D0D0D0')
    )

    # Headers
    headers = [
        "Reference No", "Direction", "Date (G.C.)", "Date (E.C.)", "Subject", "Sender/Recipient",
        "Category", "Priority", "Status", "Department", "Assigned To", "Due Date (G.C.)", "Due Date (E.C.)"
    ]
    
    for col_num, header in enumerate(headers, 1):
        cell = worksheet.cell(row=1, column=col_num, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = border

    # Data rows
    for row_num, letter in enumerate(letters, 2):
        worksheet.cell(row=row_num, column=1, value=letter.reference_no or "").border = border
        worksheet.cell(row=row_num, column=2, value=letter.get_direction_display()).border = border
        worksheet.cell(row=row_num, column=3, value=letter.date.strftime("%Y-%m-%d") if letter.date else "").border = border
        worksheet.cell(row=row_num, column=4, value=format_ethiopian_date(letter.date, fmt='full') if letter.date else "").border = border
        worksheet.cell(row=row_num, column=5, value=letter.subject).border = border
        
        sender_recipient = letter.sender if letter.direction == 'INCOMING' else letter.recipient
        worksheet.cell(row=row_num, column=6, value=sender_recipient or "").border = border
        
        worksheet.cell(row=row_num, column=7, value=letter.category.name if letter.category else "").border = border
        worksheet.cell(row=row_num, column=8, value=letter.get_priority_display()).border = border
        worksheet.cell(row=row_num, column=9, value=letter.get_status_display()).border = border
        worksheet.cell(row=row_num, column=10, value=letter.assigned_department.name if letter.assigned_department else "").border = border
        worksheet.cell(row=row_num, column=11, value=str(letter.assigned_person) if letter.assigned_person else "").border = border
        worksheet.cell(row=row_num, column=12, value=letter.due_date.strftime("%Y-%m-%d") if letter.due_date else "").border = border
        worksheet.cell(row=row_num, column=13, value=format_ethiopian_date(letter.due_date, fmt='full') if letter.due_date else "").border = border

    # Auto-adjust column widths
    column_widths = [18, 12, 12, 18, 32, 22, 15, 12, 14, 18, 18, 12, 18]
    for col_num, width in enumerate(column_widths, 1):
        worksheet.column_dimensions[openpyxl.utils.get_column_letter(col_num)].width = width

    # Add title row at the top
    worksheet.insert_rows(1)
    worksheet.merge_cells('A1:M1')
    title_cell = worksheet.cell(row=1, column=1, value=title)
    title_cell.font = Font(bold=True, size=14, color="4F46E5")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    # Add generated date
    worksheet.insert_rows(2)
    worksheet.merge_cells('A2:M2')
    eth_now = format_ethiopian_date(datetime.now().date(), fmt='full')
    date_cell = worksheet.cell(row=2, column=1, value=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} (G.C.) / {eth_now} (E.C.)")
    date_cell.font = Font(size=10, color="666666")
    date_cell.alignment = Alignment(horizontal="center", vertical="center")

    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{title.replace(" ", "_")}_{datetime.now().strftime("%Y%m%d")}.xlsx"'
    return response


def export_letters_to_pdf(letters, title="Letters Report"):
    """
    Export letters to PDF format using reportlab in landscape orientation.
    """
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{title.replace(" ", "_")}_{datetime.now().strftime("%Y%m%d")}.pdf"'

    buffer = BytesIO()
    # Use landscape A4 for rich multi-calendar table
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=25, bottomMargin=18)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#4F46E5'),
        spaceAfter=10,
        alignment=1
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.grey,
        spaceAfter=18,
        alignment=1
    )

    cell_style = ParagraphStyle(
        'CustomCell',
        parent=styles['Normal'],
        fontSize=7.5,
        leading=9
    )

    elements = []
    
    # Title
    elements.append(Paragraph(title, title_style))
    eth_now = format_ethiopian_date(datetime.now().date(), fmt='full')
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} (G.C.) | {eth_now} (E.C.)", subtitle_style))
    
    # Table data
    headers = [
        "Ref No", "Dir", "Date (GC / EC)", "Subject", "Sender / Recipient",
        "Category", "Priority", "Status", "Dept", "Assigned To", "Due Date"
    ]
    data = [[Paragraph(f"<b>{h}</b>", cell_style) for h in headers]]
    
    for letter in letters:
        greg_d = letter.date.strftime("%Y-%m-%d") if letter.date else "—"
        eth_d = format_ethiopian_date(letter.date, fmt='short') if letter.date else ""
        date_combined = f"{greg_d}<br/><font color='#4F46E5'>{eth_d}</font>" if eth_d else greg_d

        greg_due = letter.due_date.strftime("%Y-%m-%d") if letter.due_date else "—"
        eth_due = format_ethiopian_date(letter.due_date, fmt='short') if letter.due_date else ""
        due_combined = f"{greg_due}<br/><font color='#4F46E5'>{eth_due}</font>" if eth_due else greg_due

        subj_text = letter.subject[:45] + "..." if len(letter.subject) > 45 else letter.subject
        sr_text = (letter.sender if letter.direction == 'INCOMING' else letter.recipient) or "—"

        row = [
            Paragraph(letter.reference_no or "—", cell_style),
            Paragraph(letter.get_direction_display()[:3], cell_style),
            Paragraph(date_combined, cell_style),
            Paragraph(subj_text, cell_style),
            Paragraph(sr_text[:25], cell_style),
            Paragraph(letter.category.name if letter.category else "—", cell_style),
            Paragraph(letter.get_priority_display(), cell_style),
            Paragraph(letter.get_status_display(), cell_style),
            Paragraph(letter.assigned_department.code if letter.assigned_department else "—", cell_style),
            Paragraph(str(letter.assigned_person) if letter.assigned_person else "—", cell_style),
            Paragraph(due_combined, cell_style),
        ]
        data.append(row)
    
    # Create table
    col_widths = [1.0*inch, 0.5*inch, 1.2*inch, 2.3*inch, 1.4*inch, 0.8*inch, 0.7*inch, 0.8*inch, 0.6*inch, 0.9*inch, 1.1*inch]
    table = Table(data, colWidths=col_widths)
    
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
    ])
    
    table.setStyle(table_style)
    elements.append(table)
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    
    response.write(pdf)
    return response
