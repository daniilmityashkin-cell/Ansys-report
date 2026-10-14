# -*- coding: utf-8 -*-
# Окно ввода из скрипта «RVS Geometry» v1.2 (автор - научный руководитель проекта, используется с его разрешения).
# Запуск: python -m ansys_report geometry-classic   (нужен tkinter; в установщик не входит).
from __future__ import annotations
import json, math, datetime, os, sys, threading, queue, traceback, webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from .rvs_core import *
from .rvs_core import VERSION, DIAMETERS, HEIGHTS, number, integer, TankModel, make_cad, step_write, iges_write, report_write, save_metadata, thickness_groups

class DataGrid(ttk.Frame):
    """Editable numeric grid with Excel TSV paste at the active cell."""
    def __init__(self,parent,headings,data,axis_header=False):
        super().__init__(parent);self.data=[];self.active=(1,1) if axis_header else (0,0);self.axis_header=axis_header;self.editor=None
        self.tree=ttk.Treeview(self,show='headings',selectmode='extended');self.tree.grid(row=0,column=0,sticky='nsew')
        ttk.Scrollbar(self,orient='vertical',command=self.tree.yview).grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(self,orient='horizontal',command=self.tree.xview);horizontal.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=lambda a,b:self.children_scroll(a,b),xscrollcommand=horizontal.set)
        self.vscroll=self.grid_slaves(row=0,column=1)[0]
        self.columnconfigure(0,weight=1);self.rowconfigure(0,weight=1)
        bottom=ttk.Frame(self);bottom.grid(row=2,column=0,sticky='ew',pady=(6,0));self.note=ttk.Label(bottom,text='');self.note.pack(side='left')
        ttk.Button(bottom,text='Вставить из Excel',command=self.paste).pack(side='right')
        self.tree.tag_configure('axes',background='#e8eef5');self.tree.tag_configure('input',background='#fff6df')
        self.tree.bind('<Button-1>',self.click);self.tree.bind('<Double-1>',self.edit_event);self.tree.bind('<Return>',self.edit_event)
        self.tree.bind('<Control-v>',lambda e:self.paste());self.tree.bind('<Control-V>',lambda e:self.paste())
        self.tree.bind('<Control-c>',lambda e:self.copy());self.tree.bind('<Control-C>',lambda e:self.copy())
        for key,delta in [('Left',(0,-1)),('Right',(0,1)),('Up',(-1,0)),('Down',(1,0))]:self.tree.bind('<'+key+'>',lambda e,d=delta:self.move(*d))
        self.set_data(headings,data)
    def children_scroll(self,a,b):self.vscroll.set(a,b)
    @staticmethod
    def display(v):return format(float(v),'.12g') if isinstance(v,(int,float,np.number)) else str(v)
    def set_data(self,headings,data):
        self.commit();self.data=[list(r) for r in data];self.headings=list(headings);cols=[f'c{i}' for i in range(len(headings))]
        self.tree.configure(columns=cols)
        for i,(col,title) in enumerate(zip(cols,headings)):
            self.tree.heading(col,text=title);self.tree.column(col,width=112 if i==0 else 100,minwidth=70,anchor='e',stretch=False)
        self.refresh();self.active=(min(1,len(data)-1),min(1,len(cols)-1)) if self.axis_header else (0,0);self.update_note()
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for j,row in enumerate(self.data):self.tree.insert('', 'end',iid=str(j),values=[self.display(v) for v in row],tags=('axes' if self.axis_header and j==0 else 'input',))
    def update_note(self):
        r,c=self.active;self.note.configure(text=f'Начало вставки: строка {r+1}, столбец {c+1}. Двойной щелчок — ввод.')
        if self.data:self.tree.selection_set(str(r));self.tree.focus(str(r));self.tree.see(str(r))
    def click(self,e):
        self.commit();row=self.tree.identify_row(e.y);col=self.tree.identify_column(e.x)
        if row and col:self.active=(int(row),int(col[1:])-1);self.update_note()
    def move(self,dr,dc):
        self.commit();r,c=self.active;self.active=(max(0,min(len(self.data)-1,r+dr)),max(0,min(len(self.headings)-1,c+dc)));self.update_note();return 'break'
    def edit_event(self,e=None):
        self.commit();r,c=self.active
        if self.axis_header and r==0 and c==0:return 'break'
        box=self.tree.bbox(str(r),f'c{c}')
        if not box:return 'break'
        x,y,w,h=box;self.editor=ttk.Entry(self.tree);self.editor.place(x=x,y=y,width=w,height=h);self.editor.insert(0,self.display(self.data[r][c]));self.editor.select_range(0,'end');self.editor.focus_set()
        self.editor.bind('<Return>',lambda e:self.finish_edit());self.editor.bind('<Escape>',lambda e:self.cancel_edit())
        self.editor.bind('<FocusOut>',lambda e:self.commit());return 'break'
    def finish_edit(self):self.commit();self.tree.focus_set();self.move(1,0);return 'break'
    def cancel_edit(self):
        if self.editor:self.editor.destroy();self.editor=None
        self.tree.focus_set();return 'break'
    def commit(self):
        if self.editor is not None:
            editor=self.editor;self.editor=None;r,c=self.active
            try:value=editor.get();self.data[r][c]=value;self.tree.item(str(r),values=[self.display(v) for v in self.data[r]])
            finally:editor.destroy()
    def paste_text(self,text):
        self.commit();rows=[line.split('\t') for line in text.replace('\r','').rstrip('\n').split('\n')]
        if not rows or not text.strip():return
        r,c=self.active
        if r+len(rows)>len(self.data) or c+max(map(len,rows))>len(self.headings):raise ValueError('Вставляемый блок не помещается в таблицу. Выберите начальную ячейку или измените число линий.')
        for j,row in enumerate(rows):
            for i,v in enumerate(row):
                if self.axis_header and r+j==0 and c+i==0:continue
                if v.strip():number(v,f'Вставка: строка {j+1}, столбец {i+1}')
        for j,row in enumerate(rows):
            for i,v in enumerate(row):
                if not(self.axis_header and r+j==0 and c+i==0):self.data[r+j][c+i]=v.strip()
        self.refresh();self.update_note()
    def paste(self):
        try:self.paste_text(self.clipboard_get())
        except (tk.TclError,ValueError) as e:messagebox.showerror('Вставка из Excel',str(e),parent=self.winfo_toplevel())
        return 'break'
    def copy(self):
        self.commit();selected=[int(v) for v in self.tree.selection()];rows=selected or range(len(self.data))
        self.clipboard_clear();self.clipboard_append('\n'.join('\t'.join(self.display(v) for v in self.data[r]) for r in rows));return 'break'
    def matrix(self):
        self.commit();return [list(r) for r in self.data]

def matrix_data(x,y,values,label):return [[label,*x],*[[v,*row] for v,row in zip(y,values)]]

class DefectPanel(ttk.Frame):
    def __init__(self,parent,index,project=None,diameter_getter=None):
        super().__init__(parent,padding=12);self.index=index
        self.diameter_getter=diameter_getter or (lambda:39.9);self._link_busy=False
        defaults=dict(name=f'Вмятина {index}',mode='Дуга, м',anchor='0',height='9',width='2.4',span_height='3',nx='7',ny='9')
        d=project or {};defaults.update({k:str(v) for k,v in d.items() if k in defaults})
        if d:defaults.update(width=str(number(d['x'][-1])-number(d['x'][0])),span_height=str(number(d['y'][-1])-number(d['y'][0])),nx=str(len(d['x'])),ny=str(len(d['y'])))
        self.vars={k:tk.StringVar(value=v) for k,v in defaults.items()}
        self._last_anchor='angle' if defaults['mode']=='Угол, град' else 'arc'
        self.vars['arc']=tk.StringVar(value=defaults['anchor'] if self._last_anchor=='arc' else '')
        self.vars['angle']=tk.StringVar(value=defaults['anchor'] if self._last_anchor=='angle' else '')
        self.sync_anchor(self._last_anchor,mark=False)
        self.vars['arc'].trace_add('write',lambda *args:self.sync_anchor('arc'))
        self.vars['angle'].trace_add('write',lambda *args:self.sync_anchor('angle'))
        form=ttk.Frame(self);form.pack(fill='x')
        self.field(form,'Название',self.vars['name'],0,0,width=20)
        self.field(form,'Расстояние по дуге, м',self.vars['arc'],0,1)
        self.field(form,'Угол от образующей №1, °',self.vars['angle'],0,2)
        self.field(form,'Высота точки, м',self.vars['height'],0,3)
        self.field(form,'Ширина участка, м',self.vars['width'],1,0)
        self.field(form,'Высота участка, м',self.vars['span_height'],1,1)
        self.field(form,'Вертикальных линий',self.vars['nx'],1,2)
        self.field(form,'Горизонтальных линий',self.vars['ny'],1,3)
        ttk.Button(form,text='Создать сетку вмятины',command=self.build).grid(row=4,column=0,columnspan=2,sticky='w',pady=(5,9))
        ttk.Label(self,text='В ячейках — δлок, мм относительно основной стенки. Верхняя строка и левый столбец — координаты линий, м.').pack(anchor='w',pady=(0,7))
        self.grid_holder=ttk.Frame(self);self.grid_holder.pack(fill='both',expand=True);self.grid=None
        if d:self.make_grid(d['x'],d['y'],d['values'])
        else:self.build()
    def sync_anchor(self,source,mark=True):
        if self._link_busy:return
        if mark:self._last_anchor=source
        target='angle' if source=='arc' else 'arc'
        self._link_busy=True
        try:
            diameter=number(self.diameter_getter(),'Диаметр')
            if diameter<=0:raise ValueError('Диаметр должен быть положительным.')
            value=number(self.vars[source].get())
            result=value*360/(np.pi*diameter) if source=='arc' else value*np.pi*diameter/360
            self.vars[target].set(format(float(result),'.12g'))
        except ValueError:
            self.vars[target].set('')
        finally:self._link_busy=False
    @staticmethod
    def field(frame,label,var,row,col,values=None,width=16):
        ttk.Label(frame,text=label).grid(row=row*2,column=col,sticky='w',padx=(0,18),pady=(0,3))
        widget=ttk.Combobox(frame,textvariable=var,values=values,state='readonly',width=width) if values else ttk.Entry(frame,textvariable=var,width=width)
        widget.grid(row=row*2+1,column=col,sticky='ew',padx=(0,18),pady=(0,10));frame.columnconfigure(col,weight=1)
    def make_grid(self,x,y,values):
        if self.grid:self.grid.destroy()
        self.grid=DataGrid(self.grid_holder,['Z, м']+[f'Линия {i+1}' for i in range(len(x))],matrix_data(x,y,values,'s, м'),True);self.grid.pack(fill='both',expand=True)
    def build(self):
        try:
            nx=integer(self.vars['nx'].get(),'Вертикальные линии',2,160);ny=integer(self.vars['ny'].get(),'Горизонтальные линии',2,200)
            w=number(self.vars['width'].get(),'Ширина участка');h=number(self.vars['span_height'].get(),'Высота участка')
            if min(w,h)<=0:raise ValueError('Ширина и высота участка должны быть положительными.')
            if self.grid and any(str(v).strip() for row in self.grid.matrix()[1:] for v in row[1:]):
                if not messagebox.askyesno('Новая сетка','Новая сетка заменит введённые точки этой вмятины. Продолжить?',parent=self.winfo_toplevel()):return
            self.make_grid(np.linspace(-w/2,w/2,nx).tolist(),np.linspace(-h/2,h/2,ny).tolist(),[['']*nx for _ in range(ny)])
        except ValueError as e:messagebox.showerror('Сетка вмятины',str(e),parent=self.winfo_toplevel())
    def snapshot(self):
        rows=self.grid.matrix();d={k:v.get() for k,v in self.vars.items()};d.update(x=rows[0][1:],y=[r[0] for r in rows[1:]],values=[r[1:] for r in rows[1:]])
        d['mode']='Дуга, м' if self._last_anchor=='arc' else 'Угол, град';d['anchor']=self.vars[self._last_anchor].get()
        return d

class Application:
    def __init__(self,root):
        self.root=root;self.project_path=None;self.defect_panels=[];self.events=queue.Queue();self.busy=False
        root.title(f'РВС · Геометрия стенки {VERSION}');root.geometry('1120x820');root.minsize(920,660)
        style=ttk.Style(root);style.theme_use('clam');style.configure('.',font=('Segoe UI',10));style.configure('Treeview',rowheight=26,font=('Segoe UI',10));style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'))
        style.configure('Title.TLabel',font=('Segoe UI',19));style.configure('Hint.TLabel',foreground='#5b6875');style.configure('Primary.TButton',font=('Segoe UI',10,'bold'),padding=(16,9))
        main=ttk.Frame(root,padding=18);main.pack(fill='both',expand=True)
        main.columnconfigure(0,weight=1);main.rowconfigure(3,weight=1,minsize=100)
        top=ttk.Frame(main);top.grid(row=0,column=0,sticky='ew');ttk.Label(top,text='Геометрия стенки резервуара',style='Title.TLabel').pack(side='left')
        for text,command in [('Справка',self.help),('Сохранить проект',self.save),('Открыть проект',self.open)]:ttk.Button(top,text=text,command=command).pack(side='right',padx=(8,0))
        ttk.Label(main,text='Введите измерения → проверьте отчёт → экспортируйте гладкую поверхность.',style='Hint.TLabel').grid(row=1,column=0,sticky='w',pady=(4,13))
        box=ttk.LabelFrame(main,text='Размеры резервуара и измерения основной стенки',padding=12);box.grid(row=2,column=0,sticky='ew')
        self.vars={k:tk.StringVar(value=v) for k,v in dict(diameter='39.9',height='18',n='36',nz='13',nb='12',threshold='0.1',tolerance='0.1',format='STEP + IGES').items()}
        for col,(label,key,options) in enumerate([('Диаметр, м','diameter',DIAMETERS),('Высота, м','height',HEIGHTS),('Образующих','n',None),('Точек по высоте','nz',None)]):
            DefectPanel.field(box,label,self.vars[key],0,col,values=None)
            if options:
                for w in box.grid_slaves(row=1,column=col):w.destroy()
                combo=ttk.Combobox(box,textvariable=self.vars[key],values=[f'{v:g}' for v in options],width=16);combo.grid(row=1,column=col,sticky='ew',padx=(0,18),pady=(0,10))
        ttk.Button(box,text='Создать таблицу образующих',command=self.build_wall).grid(row=2,column=0,columnspan=2,sticky='w')
        ttk.Label(box,text='Углы и отметки в таблице можно уточнить. Δr в мм: + наружу, − внутрь.',style='Hint.TLabel').grid(row=2,column=2,columnspan=2,sticky='w')
        self.tabs=ttk.Notebook(main);self.tabs.grid(row=3,column=0,sticky='nsew',pady=14)
        self.wall_tab=ttk.Frame(self.tabs,padding=12);self.dents_tab=ttk.Frame(self.tabs,padding=10);self.bands_tab=ttk.Frame(self.tabs,padding=12)
        self.tabs.add(self.wall_tab,text='  1. Точки стенки  ');self.tabs.add(self.dents_tab,text='  2. Вмятины  ');self.tabs.add(self.bands_tab,text='  3. Пояса и толщины  ')
        self.includes_defects=tk.BooleanVar(value=True)
        ttk.Checkbutton(self.wall_tab,text='Точки стенки — фактические измерения, уже содержащие локальные вмятины',variable=self.includes_defects).pack(anchor='w',pady=(0,8))
        self.wall=None;self.build_wall()
        actions=ttk.Frame(self.dents_tab);actions.pack(fill='x',pady=(0,10));ttk.Button(actions,text='+ Добавить вмятину',command=self.add_defect).pack(side='left')
        ttk.Button(actions,text='Удалить выбранную',command=self.remove_defect).pack(side='left',padx=10)
        ttk.Label(actions,text='Привязка — по самой глубокой измеренной точке.',style='Hint.TLabel').pack(side='left',padx=6)
        self.dent_tabs=ttk.Notebook(self.dents_tab);self.dent_tabs.pack(fill='both',expand=True)
        bandbar=ttk.Frame(self.bands_tab);bandbar.pack(fill='x',pady=(0,10));ttk.Label(bandbar,text='Количество поясов').pack(side='left');ttk.Entry(bandbar,textvariable=self.vars['nb'],width=8).pack(side='left',padx=10)
        ttk.Button(bandbar,text='Создать таблицу поясов',command=self.build_bands).pack(side='left');self.band_summary=ttk.Label(bandbar,text='',style='Hint.TLabel');self.band_summary.pack(side='left',padx=14)
        ttk.Label(self.bands_tab,text='Начальные высоты — 1,49 м с остатком в последнем поясе. Уточните их и введите толщины, мм.',style='Hint.TLabel').pack(anchor='w',pady=(0,7))
        self.bands=None;self.build_bands()
        bottom=ttk.Frame(main);bottom.grid(row=4,column=0,sticky='ew');self.report_button=ttk.Button(bottom,text='Сгенерировать отчёт',command=lambda:self.generate('report'),style='Primary.TButton');self.report_button.pack(side='left')
        self.surface_button=ttk.Button(bottom,text='Сгенерировать поверхность',command=lambda:self.generate('surface'),style='Primary.TButton');self.surface_button.pack(side='left',padx=10)
        ttk.Combobox(bottom,textvariable=self.vars['format'],values=['STEP','IGES','STEP + IGES'],state='readonly',width=14).pack(side='left')
        ttk.Label(bottom,text='Точность CAD, мм').pack(side='left',padx=(18,5));ttk.Entry(bottom,textvariable=self.vars['tolerance'],width=7).pack(side='left')
        self.progress=ttk.Progressbar(main,mode='indeterminate');self.progress.grid(row=5,column=0,sticky='ew',pady=(12,5));self.status=ttk.Label(main,text='Готово к вводу. Двойной щелчок — редактирование; Ctrl+V — вставка из Excel.',style='Hint.TLabel',wraplength=1000);self.status.grid(row=6,column=0,sticky='ew')
        self.vars['diameter'].trace_add('write',lambda *args:self.diameter_changed())
        root.bind('<Configure>',lambda e:self.status.configure(wraplength=max(300,root.winfo_width()-40)) if e.widget==root else None)
        self.saved_snapshot=json.dumps(self.snapshot(),ensure_ascii=False,sort_keys=True)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(150,self.poll)
    def build_wall(self):
        try:
            n=integer(self.vars['n'].get(),'Количество образующих',3,160);nz=integer(self.vars['nz'].get(),'Количество точек по высоте',2,200);h=number(self.vars['height'].get(),'Высота')
            if h<=0:raise ValueError('Высота должна быть положительной.')
            if self.wall and any(str(v).strip() for r in self.wall.matrix()[1:] for v in r[1:]):
                if not messagebox.askyesno('Новая таблица','Новая таблица заменит введённые отклонения стенки. Продолжить?',parent=self.root):return
            self.set_wall(np.arange(n)*360/n,np.linspace(0,h,nz),[['']*n for _ in range(nz)])
        except ValueError as e:messagebox.showerror('Измерения стенки',str(e),parent=self.root)
    def set_wall(self,angles,z,values):
        if self.wall:self.wall.destroy()
        self.wall=DataGrid(self.wall_tab,['Z, м']+[f'№{i+1}' for i in range(len(angles))],matrix_data(angles,z,values,'φ, град'),True);self.wall.pack(fill='both',expand=True)
    def build_bands(self):
        try:
            n=integer(self.vars['nb'].get(),'Количество поясов',1,100);h=number(self.vars['height'].get(),'Высота')
            if self.bands and any(str(r[1]).strip() for r in self.bands.matrix()):
                if not messagebox.askyesno('Новая таблица','Новая таблица заменит введённые толщины. Продолжить?',parent=self.root):return
            heights=[1.49]*(n-1)+[h-1.49*(n-1)]
            if min(heights)<=0:heights=[h/n]*n
            self.set_bands([[round(v,9),''] for v in heights])
        except ValueError as e:messagebox.showerror('Пояса',str(e),parent=self.root)
    def set_bands(self,rows):
        if self.bands:self.bands.destroy()
        self.bands=DataGrid(self.bands_tab,['Высота пояса, м','Толщина, мм'],rows);self.bands.pack(fill='both',expand=True)
        self.band_summary.configure(text=f'{len(rows)} поясов · общая высота должна быть H')
    def add_defect(self,project=None):
        if len(self.defect_panels)>=20:messagebox.showerror('Вмятины','В этой версии допускается до 20 локальных участков.',parent=self.root);return
        panel=DefectPanel(self.dent_tabs,len(self.defect_panels)+1,project,lambda:self.vars['diameter'].get());self.defect_panels.append(panel);self.dent_tabs.add(panel,text=panel.vars['name'].get());self.dent_tabs.select(panel);self.tabs.select(self.dents_tab)
    def diameter_changed(self):
        for panel in self.defect_panels:panel.sync_anchor(panel._last_anchor,mark=False)
    def remove_defect(self):
        selected=self.dent_tabs.select()
        if not selected:return
        if not messagebox.askyesno('Удалить вмятину','Удалить выбранный локальный участок из проекта?',parent=self.root):return
        p=next(p for p in self.defect_panels if str(p)==selected);self.defect_panels.remove(p);self.dent_tabs.forget(p);p.destroy()
    def snapshot(self):
        rows=self.wall.matrix();return dict(version=VERSION,diameter=self.vars['diameter'].get(),height=self.vars['height'].get(),angles=rows[0][1:],heights=[r[0] for r in rows[1:]],values=[r[1:] for r in rows[1:]],bands=self.bands.matrix(),defects=[p.snapshot() for p in self.defect_panels],contour_threshold=self.vars['threshold'].get(),wall_includes_defects=self.includes_defects.get())
    def restore(self,d):
        self.vars['diameter'].set(str(d['diameter']));self.vars['height'].set(str(d['height']));self.vars['n'].set(str(len(d['angles'])));self.vars['nz'].set(str(len(d['heights'])));self.vars['nb'].set(str(len(d['bands'])));self.vars['threshold'].set(str(d.get('contour_threshold',.1)))
        self.includes_defects.set(bool(d.get('wall_includes_defects',True)))
        self.set_wall(d['angles'],d['heights'],d['values']);self.set_bands(d['bands'])
        for p in self.defect_panels:self.dent_tabs.forget(p);p.destroy()
        self.defect_panels=[]
        for p in d.get('defects',[]):self.add_defect(p)
        self.tabs.select(self.wall_tab)
        self.saved_snapshot=json.dumps(self.snapshot(),ensure_ascii=False,sort_keys=True)
    def save(self):
        path=filedialog.asksaveasfilename(parent=self.root,title='Сохранить проект с измерениями',defaultextension='.json',filetypes=[('Проект РВС','*.json')],initialfile=self.project_path.name if self.project_path else 'Резервуар.json')
        if path:
            try:
                snapshot=self.snapshot();Path(path).write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8');self.project_path=Path(path);self.saved_snapshot=json.dumps(snapshot,ensure_ascii=False,sort_keys=True);self.status.configure(text=f'Проект сохранён: {path}');return True
            except Exception as e:messagebox.showerror('Сохранение проекта',str(e),parent=self.root)
        return False
    def close(self):
        if self.busy:messagebox.showinfo('Выполняется расчёт','Дождитесь завершения генерации, затем закройте программу.',parent=self.root);return
        current=json.dumps(self.snapshot(),ensure_ascii=False,sort_keys=True)
        if current!=self.saved_snapshot:
            answer=messagebox.askyesnocancel('Сохранить изменения?','Сохранить введённые данные проекта перед закрытием?',parent=self.root)
            if answer is None:return
            if answer and not self.save():return
        self.root.destroy()
    def open(self):
        path=filedialog.askopenfilename(parent=self.root,title='Открыть проект РВС',filetypes=[('Проект РВС','*.json')])
        if path:
            try:d=json.loads(Path(path).read_text(encoding='utf-8'));self.restore(d);self.project_path=Path(path);self.status.configure(text=f'Проект открыт: {path}')
            except Exception as e:messagebox.showerror('Открытие проекта',str(e),parent=self.root)
    def generate(self,kind):
        if self.busy:return
        try:
            project=self.snapshot();model=TankModel(project);tolerance=number(self.vars['tolerance'].get(),'Точность CAD')
            if tolerance<=0:raise ValueError('Точность CAD должна быть положительной.')
        except Exception as e:messagebox.showerror('Проверьте исходные данные',str(e),parent=self.root);return
        folder=filedialog.askdirectory(parent=self.root,title='Папка для результатов',initialdir=str(self.project_path.parent if self.project_path else Path(__file__).parent))
        if not folder:return
        self.busy=True;self.report_button.configure(state='disabled');self.surface_button.configure(state='disabled');self.progress.start(10)
        format_=self.vars['format'].get()
        def work():
            try:
                out=Path(folder);save_metadata(model,out)
                if kind=='report':
                    self.events.put(('log','Восстанавливаю поля и формирую отчёт…'));path=out/'Отчёт РВС.html';report_write(path,model);self.events.put(('done',str(path)))
                else:
                    poles,tu,tv,check=make_cad(model,tolerance,lambda s:self.events.put(('log',s)))
                    groups=thickness_groups(model.bands)
                    if 'STEP' in format_:step_write(out/'Поверхность РВС.step',poles,tu,tv,groups)
                    if 'IGES' in format_:iges_write(out/'Поверхность РВС.igs',poles,tu,tv,groups)
                    save_metadata(model,out,check);self.events.put(('done',f'Оболочка сохранена: {folder}. Участков толщины: {len(groups)}. Ошибка проверки {check["max_error_mm"]:.4f} мм.'))
            except Exception as e:
                try:(Path(folder)/'Ошибка.txt').write_text(traceback.format_exc(),encoding='utf-8')
                except OSError:pass
                self.events.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()
    def poll(self):
        while not self.events.empty():
            kind,text=self.events.get();self.status.configure(text=text)
            if kind in ['done','error']:
                self.busy=False;self.progress.stop();self.report_button.configure(state='normal');self.surface_button.configure(state='normal')
                if kind=='error':messagebox.showerror('Не удалось выполнить операцию',text,parent=self.root)
                elif text.lower().endswith('.html'):webbrowser.open(Path(text).resolve().as_uri())
                else:messagebox.showinfo('Поверхность готова',text+'\n\nЕдиницы: мм. Масштаб 1:1. Толщина каждого участка — в Участки толщины.csv. Назначьте её соответствующим поверхностям в ANSYS.',parent=self.root)
        self.root.after(150,self.poll)
    def help(self):
        top=tk.Toplevel(self.root);top.title('Как работать с программой');top.geometry('760x570');text=tk.Text(top,wrap='word',font=('Segoe UI',11),padx=18,pady=18);text.pack(fill='both',expand=True)
        text.insert('end',HELP_TEXT);text.configure(state='disabled')

HELP_TEXT='''1. Размеры и стенка
Выберите диаметр и высоту или введите собственные значения. Задайте число образующих и число отметок по высоте, затем создайте таблицу. По умолчанию углы равномерны; отметки идут от 0 до H. Уточняйте координаты в первой строке и первом столбце.
Если точки стенки уже содержат деформацию локальных участков, оставьте галочку на вкладке «Точки стенки»: программа исключит повторный учёт вмятин и сохранит совпадение с измеренными точками. Если вы вводите отдельно основную геометрию без локальных дефектов, снимите галочку.

2. Ввод из Excel
Выделите блок чисел в Excel, скопируйте. Щёлкните начальную ячейку таблицы программы и нажмите Ctrl+V или «Вставить из Excel». Для данных без координат начало — строка 2, столбец 2. Десятичная запятая и точка принимаются. Двойной щелчок — ручной ввод; Enter — следующая строка. Пустая ячейка не равна нулю.

3. Вмятины
Добавьте участок. Привязка — по самой глубокой ИЗМЕРЕННОЙ точке: расстояние по дуге или угол от образующей №1 и высота. Введите ширину, высоту участка, число вертикальных и горизонтальных линий. Таблица содержит δлок относительно основной стенки, в мм; её координаты задают положение линий внутри участка. Программа находит наиболее отрицательную точку и совмещает её с заданной привязкой. При одинаковых минимумах выбирается точка, ближайшая к середине сетки. Для выпучины без отрицательных значений используется максимум. Вокруг измеренного участка добавляется плавный переход к основной стенке шириной два крайних шага; это допущение обработки, а не дополнительные измерения.
Расстояние и угол вводятся в отдельных полях и автоматически пересчитываются по s = πDφ/360. При изменении диаметра сохраняется последнее введённое вами поле; второе пересчитывается.

4. Пояса
Введите число поясов, уточните высоты и толщины. Сумма высот должна быть равна H. Соседние пояса одинаковой толщины объединяются в один участок поверхности. Разные группы имеют общие рёбра и входят в одну оболочку. Например, толщины 13/12/12/11/11 дают три поверхности. Повторяющиеся толщины в несоседних поясах не объединяются через промежуточные пояса. Таблица «Участки толщины.csv» указывает границы и толщину каждой поверхности. STEP/IGES не добавляет объёмную толщину: оболочечные свойства назначаются этим участкам в ANSYS.

5. Отчёт и экспорт
Отчёт содержит точки, окрашенную 3D-поверхность, развёртку с нулевыми изолиниями, увеличенные прямоугольные участки и таблицу поясов. Вмятины на подробных рисунках не вращаются вместе с резервуаром. P — точка привязки, C — центр площади контура. Контур выделяется по |δлок| = 0,1 мм (порог обработки).
Экспорт создаёт одну связную оболочку из гладких B-сплайн поверхностей по группам толщины в STEP/IGES, единицы мм, без визуального усиления. Разделение использует общую геометрию и общие граничные рёбра, без повторной интерполяции участков. Погрешность проверяется в дополнительных точках, включая локальные участки. Это не оценка погрешности измерений и не проверка прочности.

6. Файлы
Скрипт не скачивает библиотеки. Нужны Python, NumPy и стандартный tkinter. Проект можно сохранить в JSON и продолжить позже. При генерации файлы с одинаковыми именами в выбранной папке заменяются; используйте отдельные папки для вариантов.
'''

def main():
    root=tk.Tk();Application(root);root.mainloop()

if __name__=='__main__':main()

