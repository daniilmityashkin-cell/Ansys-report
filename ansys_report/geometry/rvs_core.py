# -*- coding: utf-8 -*-
# Исходный алгоритм: скрипт «RVS Geometry» v1.2 (rvs_geometry_1.py), автор - научный руководитель проекта.
# Включён в проект с разрешения автора. Ядро расчёта оставлено без изменений, кроме:
#   - убран импорт tkinter (ядро работает без окна, окно вынесено в rvs_gui.py);
#   - при отсутствии NumPy выбрасывается понятное исключение.
"""RVS Geometry — один скрипт. Python 3.10+, NumPy, стандартный tkinter.

Ввод в таблицы: числа, десятичная запятая или точка; вставка TSV из Excel.
Расчёт: периодические / естественные кубические сплайны, радиальные δ.
Экспорт: связная оболочка с участками по толщине STEP / IGES, мм, 1:1.
Толщины поясов — свойства оболочки, сохраняются отдельно от CAD-поверхности.
"""
from __future__ import annotations
import json, math, datetime, html, os, sys, threading, queue, traceback, webbrowser
from pathlib import Path
try:
    import numpy as np
except ImportError as e:
    raise ImportError('Не найден NumPy. Установите: python -m pip install numpy') from e

VERSION='1.2'
DIAMETERS=[4.73,6.63,7.58,8.53,10.43,15.18,18.98,20.92,22.8,28.5,34.2,39.9,45.6,47.4,56.9,60.7,95.4]
HEIGHTS=[6,7.5,9,12,15,18]

def number(value,where='Значение'):
    if isinstance(value,bool) or isinstance(value,(datetime.date,datetime.time)):
        raise ValueError(f'{where}: требуется число, не дата.')
    try:
        result=float(str(value).strip().replace('\u00a0','').replace(' ','').replace(',','.'))
    except (ValueError,TypeError):raise ValueError(f'{where}: введите число. Пустые ячейки и даты не допускаются.') from None
    if not math.isfinite(result):raise ValueError(f'{where}: число должно быть конечным.')
    return result

def integer(value,where,minimum=1,maximum=500):
    v=number(value,where)
    if v!=int(v) or not minimum<=v<=maximum:raise ValueError(f'{where}: целое число от {minimum} до {maximum}.')
    return int(v)

def spline_second(x,values,period=None):
    x=np.asarray(x,float);v=np.asarray(values,float);n=len(x)
    if n<2 or np.any(np.diff(x)<=0):raise ValueError('Координаты линий должны строго возрастать.')
    flat=v.reshape(n,-1);A=np.zeros((n,n));rhs=np.zeros_like(flat)
    if period is None:
        A[0,0]=A[-1,-1]=1
        for i in range(1,n-1):
            a=x[i]-x[i-1];b=x[i+1]-x[i];A[i,i-1:i+2]=[a,2*(a+b),b]
            rhs[i]=6*((flat[i+1]-flat[i])/b-(flat[i]-flat[i-1])/a)
    else:
        if x[-1]-x[0]>=period:raise ValueError('Углы не должны содержать дублирующую образующую 360°.')
        for i in range(n):
            a=(x[i]-x[(i-1)%n])%period;b=(x[(i+1)%n]-x[i])%period
            A[i,(i-1)%n]+=a;A[i,i]+=2*(a+b);A[i,(i+1)%n]+=b
            rhs[i]=6*((flat[(i+1)%n]-flat[i])/b-(flat[i]-flat[(i-1)%n])/a)
    return np.linalg.solve(A,rhs).reshape(v.shape)

class Spline:
    def __init__(self,x,values,period=None):
        self.x=np.asarray(x,float);self.v=np.asarray(values,float);self.period=period
        self.m=spline_second(self.x,self.v,period)
    def locate(self,q):
        q=np.asarray(q,float)
        if self.period is not None:q=(q-self.x[0])%self.period+self.x[0]
        i=np.searchsorted(self.x,q,side='right')-1;i=np.clip(i,0,len(self.x)-1 if self.period else len(self.x)-2)
        k=(i+1)%len(self.x);right=np.where(k==0,self.x[0]+(self.period or 0),self.x[k]);h=right-self.x[i];b=(q-self.x[i])/h
        return i,k,h,1-b,b
    def __call__(self,q):
        i,k,h,a,b=self.locate(q);tail=(None,)*(self.v.ndim-1)
        a=a[(...,)+tail];b=b[(...,)+tail];h=h[(...,)+tail]
        return a*self.v[i]+b*self.v[k]+h*h/6*((a**3-a)*self.m[i]+(b**3-b)*self.m[k])

def paired_spline(x,v,m,q):
    q=np.asarray(q);i=np.clip(np.searchsorted(x,q,side='right')-1,0,len(x)-2);j=np.arange(len(q));h=x[i+1]-x[i];b=(q-x[i])/h;a=1-b
    return a*v[i,j]+b*v[i+1,j]+h*h/6*((a**3-a)*m[i,j]+(b**3-b)*m[i+1,j])

class LocalDefect:
    def __init__(self,d,R,H,index):
        self.id=index;self.name=str(d.get('name',f'Вмятина {index}'));self.R=R
        self.x=np.asarray([number(v,f'{self.name}: координата s') for v in d['x']],float)
        self.y=np.asarray([number(v,f'{self.name}: координата Z') for v in d['y']],float)
        self.values=np.asarray([[number(v,f'{self.name}, строка {j+1}, столбец {i+1}') for i,v in enumerate(row)] for j,row in enumerate(d['values'])])
        if self.values.shape!=(len(self.y),len(self.x)) or min(self.values.shape)<2:raise ValueError(f'{self.name}: несогласованные размеры сетки.')
        if np.any(np.diff(self.x)<=0) or np.any(np.diff(self.y)<=0):raise ValueError(f'{self.name}: координаты линий должны возрастать.')
        if self.x[-1]-self.x[0]>=2*np.pi*R:raise ValueError(f'{self.name}: ширина участка должна быть меньше периметра.')
        extreme=np.min(self.values) if np.min(self.values)<0 else np.max(self.values)
        locations=np.argwhere(np.isclose(self.values,extreme,atol=1e-10,rtol=0));middle=np.array(self.values.shape)/2
        self.peak_j,self.peak_i=locations[np.argmin(np.sum((locations-middle)**2,axis=1))]
        self.sc=number(d['anchor'],f'{self.name}: положение глубокой точки')
        if d.get('mode','Дуга, м')=='Угол, град':self.sc=np.radians(self.sc)*R
        self.sc%=2*np.pi*R;self.zc=number(d['height'],f'{self.name}: высота глубокой точки')
        self.xp=float(self.x[self.peak_i]);self.yp=float(self.y[self.peak_j])
        lo=self.zc+self.y[0]-self.yp;hi=self.zc+self.y[-1]-self.yp
        if lo< -1e-8 or hi>H+1e-8:raise ValueError(f'{self.name}: измеренный участок по высоте выходит за стенку 0…{H:g} м.')
        # Two additional zero lines outside the measured patch provide a C2 collar.
        dx0=self.x[1]-self.x[0];dx1=self.x[-1]-self.x[-2];dy0=self.y[1]-self.y[0];dy1=self.y[-1]-self.y[-2]
        self.xx=np.r_[self.x[0]-2*dx0,self.x[0]-dx0,self.x,self.x[-1]+dx1,self.x[-1]+2*dx1]
        self.yy=np.r_[self.y[0]-2*dy0,self.y[0]-dy0,self.y,self.y[-1]+dy1,self.y[-1]+2*dy1]
        pad=np.pad(self.values,2);self.v=pad;self.mx=spline_second(self.xx,pad.T);self.my=spline_second(self.yy,pad);self.mxy=spline_second(self.xx,self.my.T)
        self.sign=-1 if extreme<0 else 1
    @staticmethod
    def fade(q,lo,hi,outerlo,outerhi):
        t=np.maximum(np.clip((lo-q)/(lo-outerlo),0,1),np.clip((q-hi)/(outerhi-hi),0,1))
        return 1-10*t**3+15*t**4-6*t**5
    def evaluate(self,s,z):
        shape=np.broadcast_shapes(np.shape(s),np.shape(z));S=np.broadcast_to(s,shape).ravel();Z=np.broadcast_to(z,shape).ravel()
        x=(S-self.sc+np.pi*self.R)%(2*np.pi*self.R)-np.pi*self.R+self.xp;y=Z-self.zc+self.yp
        result=np.zeros_like(x);mask=(x>=self.xx[0])&(x<=self.xx[-1])&(y>=self.yy[0])&(y<=self.yy[-1])
        if mask.any():
            q=x[mask];zz=y[mask];i=np.clip(np.searchsorted(self.xx,q,side='right')-1,0,len(self.xx)-2);h=self.xx[i+1]-self.xx[i];b=(q-self.xx[i])/h;a=1-b
            v=a*self.v[:,i]+b*self.v[:,i+1]+h*h/6*((a**3-a)*self.mx[i].T+(b**3-b)*self.mx[i+1].T)
            m=a*self.my[:,i]+b*self.my[:,i+1]+h*h/6*((a**3-a)*self.mxy[i].T+(b**3-b)*self.mxy[i+1].T)
            result[mask]=paired_spline(self.yy,v,m,zz)*self.fade(q,self.x[0],self.x[-1],self.xx[0],self.xx[-1])*self.fade(zz,self.y[0],self.y[-1],self.yy[0],self.yy[-1])
        return result.reshape(shape)

class TankModel:
    def __init__(self,project):
        self.project=project;self.D=number(project['diameter'],'Диаметр');self.H=number(project['height'],'Высота');self.R=self.D/2;self.C=np.pi*self.D
        if self.D<=0 or self.H<=0:raise ValueError('Диаметр и высота должны быть положительными.')
        self.theta=np.radians([number(v,'Угол образующей') for v in project['angles']]);self.z=np.asarray([number(v,'Отметка по высоте') for v in project['heights']])
        self.values=np.asarray([[number(v,f'Стенка, строка {j+1}, образующая {i+1}') for i,v in enumerate(row)] for j,row in enumerate(project['values'])])
        if len(self.theta)<3 or len(self.z)<2 or self.values.shape!=(len(self.z),len(self.theta)):raise ValueError('Для стенки нужны минимум 3 образующие и 2 высотные отметки.')
        if abs(self.theta[0])>1e-9 or self.theta[-1]>=2*np.pi or np.any(np.diff(self.theta)<=0):raise ValueError('Углы: первая образующая 0°, далее возрастающие значения меньше 360°.')
        if abs(self.z[0])>1e-9 or abs(self.z[-1]-self.H)>1e-8 or np.any(np.diff(self.z)<=0):raise ValueError('Отметки по высоте: от 0 до H, строго возрастающие.')
        self.threshold=number(project.get('contour_threshold',.1),'Порог контура')
        if self.threshold<=0:raise ValueError('Порог контура должен быть больше нуля.')
        self.defects=[LocalDefect(d,self.R,self.H,i+1) for i,d in enumerate(project.get('defects',[]))]
        self.includes_defects=bool(project.get('wall_includes_defects',True))
        S,Z=np.meshgrid(self.theta*self.R,self.z);local_nodes=np.zeros_like(self.values)
        for d in self.defects:local_nodes+=d.evaluate(S,Z)
        background=self.values-local_nodes if self.includes_defects else self.values
        self.angular=Spline(self.theta,background.T,period=2*np.pi)
        self.bands=[];level=0.
        for i,b in enumerate(project['bands'],1):
            height=number(b[0],f'Пояс {i}: высота');thick=number(b[1],f'Пояс {i}: толщина')
            if min(height,thick)<=0:raise ValueError(f'Пояс {i}: высота и толщина должны быть положительными.')
            self.bands.append(dict(number=i,bottom_m=level,top_m=level+height,height_m=height,thickness_mm=thick));level+=height
        if not self.bands or abs(level-self.H)>1e-6:raise ValueError(f'Сумма высот поясов {level:g} м должна равняться высоте резервуара {self.H:g} м.')
        source=self.field(self.theta,self.z)
        expected=self.values if self.includes_defects else self.values+local_nodes
        self.point_error=float(np.max(abs(source-expected)))
    def field(self,theta,z):
        theta=np.asarray(theta,float);z=np.asarray(z,float);v=self.angular(theta).T;m=spline_second(self.z,v)
        i=np.clip(np.searchsorted(self.z,z,side='right')-1,0,len(self.z)-2);h=self.z[i+1]-self.z[i];b=(z-self.z[i])/h;a=1-b
        out=a[:,None]*v[i]+b[:,None]*v[i+1]+h[:,None]**2/6*((a[:,None]**3-a[:,None])*m[i]+(b[:,None]**3-b[:,None])*m[i+1])
        S,Z=np.meshgrid(theta*self.R,z)
        for d in self.defects:out+=d.evaluate(S,Z)
        if np.any(self.R+out/1000<=0):raise ValueError('Введённые отклонения дают неположительный радиус.')
        return out
    def paired(self,theta,z):
        theta=np.asarray(theta,float);z=np.asarray(z,float);v=self.angular(theta).T;m=spline_second(self.z,v)
        out=paired_spline(self.z,v,m,z)
        for d in self.defects:out+=d.evaluate(theta*self.R,z)
        return out

def basis(t,k,x,derivative=0):
    """B-spline basis (including one-sided endpoint derivatives), NumPy only."""
    t=np.asarray(t);x=float(x)
    if derivative:
        low=basis(t,k-1,x,derivative-1);n=len(t)-k-1;out=np.zeros(n)
        a=t[k:k+n]-t[:n];b=t[k+1:k+1+n]-t[1:n+1]
        out+=np.divide(k*low[:n],a,out=np.zeros(n),where=a!=0)
        out-=np.divide(k*low[1:n+1],b,out=np.zeros(n),where=b!=0)
        return out
    n0=len(t)-1;v=np.zeros(n0);span=np.searchsorted(t,x,side='right')-1
    if x>=t[-1]:span=np.searchsorted(t,t[-1],side='left')-1
    v[max(0,min(n0-1,span))]=1
    for p in range(1,k+1):
        n=len(t)-p-1;a=t[p:p+n]-t[:n];b=t[p+1:p+1+n]-t[1:n+1]
        v=np.divide((x-t[:n])*v[:n],a,out=np.zeros(n),where=a!=0)+np.divide((t[p+1:p+1+n]-x)*v[1:n+1],b,out=np.zeros(n),where=b!=0)
    return v

def fit_axis(x,values,periodic=False):
    x=np.asarray(x,float);t=np.r_[np.repeat(x[0],4),x[1:-1],np.repeat(x[-1],4)];n=len(t)-4
    A=np.zeros((n,n));A[:len(x)]=np.array([basis(t,3,v) for v in x]);rhs=np.zeros((n,)+values.shape[1:]);rhs[:len(x)]=values
    if periodic:
        A[-2]=basis(t,3,x[0],1)-basis(t,3,x[-1],1);A[-1]=basis(t,3,x[0],2)-basis(t,3,x[-1],2)
    else:A[-2]=basis(t,3,x[0],2);A[-1]=basis(t,3,x[-1],2)
    c=np.linalg.solve(A,rhs.reshape(n,-1)).reshape(rhs.shape)
    return t,c

def cad_value(poles,tu,tv,u,v):
    a=basis(tu,3,u);b=basis(tv,3,v);i=np.flatnonzero(abs(a)>1e-14);j=np.flatnonzero(abs(b)>1e-14)
    return np.einsum('i,ijc,j->c',a[i],poles[np.ix_(i,j)],b[j])

def make_cad(model,tolerance=.1,log=print,max_nt=None,max_nz=None):
    # Resolution follows actual measurement spacing; error checked off-grid. max_nt/max_nz ограничивают начальную сетку (модель для сеточного расчёта).
    nt=max(96,len(model.theta)*4);nz=max(33,len(model.z)*4)
    for d in model.defects:
        nt=max(nt,int(math.ceil(model.C/(np.min(np.diff(d.x))/2))))
        nz=max(nz,int(math.ceil(model.H/(np.min(np.diff(d.y))/2)))+1)
    if max_nt:nt=min(nt,max_nt)
    if max_nz:nz=min(nz,max_nz)
    tests=[(float(t),float(z)) for t in np.linspace(.0001,2*np.pi-.0001,20) for z in np.linspace(0,model.H,9)]
    tests.extend((float(t),float(z)) for t in model.theta for z in model.z)
    for d in model.defects:
        tests.extend((float((d.sc+x-d.xp)/model.R%(2*np.pi)),float(d.zc+y-d.yp)) for x in d.x for y in d.y)
        for x in np.linspace(d.xx[0],d.xx[-1],17):
            for y in np.linspace(d.yy[0],d.yy[-1],17):
                z=d.zc+y-d.yp
                if 0<=z<=model.H:tests.append((((d.sc+x-d.xp)/model.R)%(2*np.pi),z))
    ts=np.array(tests);dr=model.paired(ts[:,0],ts[:,1]);r=(model.R+dr/1000)*1000
    reference=np.column_stack([r*np.cos(ts[:,0]),r*np.sin(ts[:,0]),ts[:,1]*1000])
    for attempt in range(3):
        if nt>1800 or nz>600 or (nt+3)*(nz+2)>700000:raise ValueError('Для заданной детализации нужна слишком большая CAD-сетка. Проверьте шаги измерений и размеры участка.')
        log(f'CAD-сетка: {nt} интервалов по окружности × {nz-1} по высоте…')
        theta=np.linspace(0,2*np.pi,nt+1);z=np.linspace(0,model.H,nz);f=model.field(theta,z).T;r=(model.R+f/1000)*1000
        xyz=np.stack([r*np.cos(theta[:,None]),r*np.sin(theta[:,None]),np.broadcast_to(z[None,:]*1000,r.shape)],axis=-1);xyz[-1]=xyz[0]
        tu,cu=fit_axis(theta,xyz,True);tv,cv=fit_axis(z,np.moveaxis(cu,1,0),False);poles=np.moveaxis(cv,0,1)
        errors=[np.linalg.norm(cad_value(poles,tu,tv,t,zz)-ref) for (t,zz),ref in zip(tests,reference)];err=float(max(errors))
        seam_errors=[float(np.max(abs(np.einsum('i,ijc->jc',basis(tu,3,0,k)-basis(tu,3,2*np.pi,k),poles)))) for k in range(3)];seam=max(seam_errors)
        log(f'Проверка CAD: ошибка {err:.4f} мм; замыкание и производные {seam:.3g}.')
        if err<=tolerance:
            return poles,tu,tv,dict(max_error_mm=err,tolerance_mm=tolerance,check_points=len(tests),seam_position_error_mm=seam_errors[0],seam_d1_error_mm_per_rad=seam_errors[1],seam_d2_error_mm_per_rad2=seam_errors[2],theta_intervals=nt,height_intervals=nz-1,units='mm',scale=1)
        nt*=2;nz=2*nz-1
    raise ValueError(f'Не достигнута точность экспорта {tolerance:g} мм. Последняя ошибка {err:.4f} мм.')

def real(v):
    s=format(float(v),'.14g').upper()
    if '.' not in s and 'E' not in s:s+='.'
    return s

def thickness_groups(bands):
    """Merge only adjacent belts; equal separated thicknesses remain separate."""
    groups=[]
    for band in bands:
        if groups and math.isclose(groups[-1]['thickness_mm'],band['thickness_mm'],rel_tol=0,abs_tol=1e-9):
            groups[-1]['top_m']=band['top_m'];groups[-1]['last_belt']=band['number']
        else:groups.append(dict(index=len(groups)+1,first_belt=band['number'],last_belt=band['number'],bottom_m=band['bottom_m'],top_m=band['top_m'],thickness_mm=band['thickness_mm']))
    return groups

def step_write(path,poles,tu,tv,groups):
    """STEP AP214: one open shell, separate faces with shared boundary edges."""
    lines=[]
    def add(s):lines.append(f'#{len(lines)+1}={s};');return len(lines)
    app=add("APPLICATION_CONTEXT('automotive design')");add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app})")
    pc=add(f"PRODUCT_CONTEXT('',#{app},'mechanical')");prod=add(f"PRODUCT('RVS','RVS wall','',(#{pc}))");form=add(f"PRODUCT_DEFINITION_FORMATION('','',#{prod})")
    ctx=add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')");definition=add(f"PRODUCT_DEFINITION('design','',#{form},#{ctx})");shape=add(f"PRODUCT_DEFINITION_SHAPE('','',#{definition})")
    length=add('(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))');angle=add('(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))');solid=add('(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())')
    uncertainty=add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-5),#{length},'distance_accuracy_value','')")
    context=add(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{uncertainty})) GLOBAL_UNIT_ASSIGNED_CONTEXT((#{length},#{angle},#{solid})) REPRESENTATION_CONTEXT('',''))")
    ids=[]
    for row in poles:
        ids.append([add("CARTESIAN_POINT('',("+','.join(real(x) for x in p)+'))') for p in row])
    uk,um=np.unique(tu,return_counts=True);vk,vm=np.unique(tv,return_counts=True)
    grid='('+','.join('('+','.join(f'#{v}' for v in row)+')' for row in ids)+')'
    ints=lambda v:'('+','.join(str(int(x)) for x in v)+')';floats=lambda v:'('+','.join(real(x) for x in v)+')'
    surface=add(f"B_SPLINE_SURFACE_WITH_KNOTS('',3,3,{grid},.UNSPECIFIED.,.T.,.F.,.F.,{ints(um)},{ints(vm)},{floats(uk)},{floats(vk)},.UNSPECIFIED.)")
    paramctx=add("(GEOMETRIC_REPRESENTATION_CONTEXT(2) PARAMETRIC_REPRESENTATION_CONTEXT() REPRESENTATION_CONTEXT('2D SPACE',''))")
    def point(coords):return add("CARTESIAN_POINT('',("+','.join(real(x) for x in coords)+'))')
    def curve(coords,knots,closed,name):
        pts=[point(p) for p in coords];kk,mm=np.unique(knots,return_counts=True)
        return add(f"B_SPLINE_CURVE_WITH_KNOTS('{name}',3,({','.join('#'+str(p) for p in pts)}),.UNSPECIFIED.,{'.T.' if closed else '.F.'},.F.,{ints(mm)},{floats(kk)},.UNSPECIFIED.)")
    def pcurve(u,v,dx,dy):
        p=point([u,v]);direction=add("DIRECTION('',("+real(dx)+','+real(dy)+'))');vector=add(f"VECTOR('',#{direction},1.)");line=add(f"LINE('',#{p},#{vector})")
        rep2=add(f"DEFINITIONAL_REPRESENTATION('',(#{line}),#{paramctx})")
        return add(f"PCURVE('',#{surface},#{rep2})")
    levels=[groups[0]['bottom_m']]+[g['top_m'] for g in groups];vertices=[];rings=[]
    for i,v in enumerate(levels):
        coordinates=np.einsum('j,ijc->ic',basis(tv,3,v),poles)
        vertex=add(f"VERTEX_POINT('',#{point(cad_value(poles,tu,tv,tu[3],v))})");vertices.append(vertex)
        geom=curve(coordinates,tu,True,f'Ring_{i:02d}');pc=pcurve(tu[3],v,1,0)
        sc=add(f"SURFACE_CURVE('',#{geom},(#{pc}),.PCURVE_S1.)")
        rings.append(add(f"EDGE_CURVE('',#{vertex},#{vertex},#{sc},.T.)"))
    seam_geometry=curve(np.einsum('i,ijc->jc',basis(tu,3,tu[3]),poles),tv,False,'Seam')
    faces=[]
    for i,g in enumerate(groups):
        bottom=g['bottom_m'];top=g['top_m']
        trim=add(f"TRIMMED_CURVE('',#{seam_geometry},(PARAMETER_VALUE({real(bottom)})),(PARAMETER_VALUE({real(top)})),.T.,.PARAMETER.)")
        right=pcurve(tu[-4],0,0,1);left=pcurve(tu[3],0,0,1)
        seam=add(f"SEAM_CURVE('',#{trim},(#{right},#{left}),.PCURVE_S1.)")
        edge=add(f"EDGE_CURVE('',#{vertices[i]},#{vertices[i+1]},#{seam},.T.)")
        oriented=[add(f"ORIENTED_EDGE('',*,*,#{e},{'.T.' if orientation else '.F.'})") for e,orientation in [(rings[i],True),(edge,True),(rings[i+1],False),(edge,False)]]
        loop=add("EDGE_LOOP('',("+','.join('#'+str(e) for e in oriented)+'))');bound=add(f"FACE_OUTER_BOUND('',#{loop},.T.)")
        name=f"Zone_{i+1:02d}_belts_{g['first_belt']}-{g['last_belt']}_t{g['thickness_mm']:g}mm"
        faces.append(add(f"ADVANCED_FACE('{name}',(#{bound}),#{surface},.T.)"))
    shell=add("OPEN_SHELL('RVS wall',("+','.join('#'+str(f) for f in faces)+'))')
    geom=add(f"SHELL_BASED_SURFACE_MODEL('RVS wall',(#{shell}))");rep=add(f"MANIFOLD_SURFACE_SHAPE_REPRESENTATION('RVS wall',(#{geom}),#{context})");add(f'SHAPE_DEFINITION_REPRESENTATION(#{shape},#{rep})')
    stamp=datetime.datetime.now().isoformat(timespec='seconds')
    header=f"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('RVS wall surface'),'2;1');\nFILE_NAME('RVS','{stamp}',(''),(''),'RVS Geometry {VERSION}','','');\nFILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\nENDSEC;\nDATA;\n"
    Path(path).write_text(header+'\n'.join(lines)+'\nENDSEC;\nEND-ISO-10303-21;\n',encoding='ascii')

def iges_write(path,poles,tu,tv,groups):
    """IGES 5.3 BRep: entity 514 open shell, 510 faces, shared 504 edges."""
    nu,nv=poles.shape[:2]
    entities=[]
    def add(type_,fields,form=0,label='',root=False,parametric=False):
        pointer=2*len(entities)+1
        entities.append(dict(type=type_,fields=[str(type_),*map(str,fields)],form=form,label=label,root=root,parametric=parametric,pointer=pointer))
        return pointer
    fields=['128',str(nu-1),str(nv-1),'3','3','1','0','1','0','0']
    fields +=[real(v) for v in tu]+[real(v) for v in tv]+['1.']*(nu*nv)
    fields +=[real(v) for p in np.moveaxis(poles,0,1).reshape(-1,3) for v in p]
    fields +=[real(tu[3]),real(tu[-4]),real(tv[3]),real(tv[-4])]
    surface=add(128,fields[1:],label='WALL')
    levels=[groups[0]['bottom_m']]+[g['top_m'] for g in groups]
    vertices=add(502,[len(levels),*[real(x) for v in levels for x in cad_value(poles,tu,tv,tu[3],v)]],form=1,label='VERTICES')
    def curve(coords,knots,lo,hi,closed,label):
        fields=[len(coords)-1,3,0,int(closed),1,0,*[real(v) for v in knots],*['1.']*len(coords),*[real(v) for p in coords for v in p],real(lo),real(hi),'0.','0.','0.']
        return add(126,fields,label=label)
    rings=[]
    for i,v in enumerate(levels):rings.append(curve(np.einsum('j,ijc->ic',basis(tv,3,v),poles),tu,tu[3],tu[-4],True,f'RING{i}'))
    seam_poles=np.einsum('i,ijc->jc',basis(tu,3,tu[3]),poles)
    seams=[curve(seam_poles,tv,g['bottom_m'],g['top_m'],False,f'SEAM{i}') for i,g in enumerate(groups)]
    edge_fields=[len(rings)+len(seams)]
    for i,c in enumerate(rings):edge_fields.extend([c,vertices,i+1,vertices,i+1])
    for i,c in enumerate(seams):edge_fields.extend([c,vertices,i+1,vertices,i+2])
    edges=add(504,edge_fields,form=1,label='EDGES')
    def line(u0,v0,u1,v1):return add(110,[real(u0),real(v0),'0.',real(u1),real(v1),'0.'],parametric=True)
    faces=[]
    for i,g in enumerate(groups):
        bottom=g['bottom_m'];top=g['top_m'];umin=tu[3];umax=tu[-4]
        pcurves=[line(umin,bottom,umax,bottom),line(umax,bottom,umax,top),line(umin,top,umax,top),line(umin,bottom,umin,top)]
        tuples=[(i+1,1),(len(rings)+i+1,1),(i+2,0),(len(rings)+i+1,0)]
        loop_fields=[4]
        for (index,orientation),pc in zip(tuples,pcurves):loop_fields.extend([0,edges,index,orientation,1,1,pc])
        loop=add(508,loop_fields,form=1,label=f'LOOP{i+1}')
        faces.append(add(510,[surface,1,1,loop],form=1,label=f'T{g["thickness_mm"]:g}'[:8]))
    add(514,[len(faces),*[v for face in faces for v in (face,1)]],form=2,label='RVS',root=True)
    pdata=[];directory=[]
    for entity in entities:
        first=len(pdata)+1;lines_=[];current=''
        for i,field in enumerate(entity['fields']):
            token=field+(';' if i==len(entity['fields'])-1 else ',')
            if len(current)+len(token)>64:lines_.append(current);current=''
            current+=token
        if current:lines_.append(current)
        ptr=entity['pointer'];status=f'00{0 if entity["root"] else 1:02d}{5 if entity["parametric"] else 0:02d}00'
        d1=[entity['type'],first,0,0,0,0,0,0,status];d2=[entity['type'],0,0,len(lines_),entity['form'],0,0,entity['label'],0]
        directory.extend([''.join(f'{v:8}' for v in d1)+'D'+f'{ptr:7}',''.join(f'{v:8}' for v in d2)+'D'+f'{ptr+1:7}'])
        pdata.extend(f'{v:64}{ptr:8}P{i:7}' for i,v in enumerate(lines_,first))
    now=datetime.datetime.now().strftime('%Y%m%d.%H%M%S')
    globals_=f'1H,,1H;,12HRVS Geometry,8Hwall.igs,6HPython,12HRVS Geometry,32,38,6,308,15,12HRVS Geometry,1.0,2,2HMM,1,0.1,15H{now},1.E-5,1.E8,0H,0H,11,0,15H{now};'
    gs=[globals_[i:i+72] for i in range(0,len(globals_),72)]
    lines=[f'{"RVS wall surface":72}S{1:7}']+[f'{v:72}G{i:7}' for i,v in enumerate(gs,1)]
    lines.extend(directory);lines.extend(pdata)
    lines.append(f'S{1:7}G{len(gs):7}D{len(directory):7}P{len(pdata):7}'.ljust(72)+'T'+f'{1:7}')
    Path(path).write_text('\n'.join(lines)+'\n',encoding='ascii')

def save_metadata(model,out,check=None):
    Path(out).mkdir(exist_ok=True,parents=True)
    (Path(out)/'Проект.json').write_text(json.dumps(model.project,ensure_ascii=False,indent=2),encoding='utf-8')
    (Path(out)/'Пояса.csv').write_text('Пояс;Низ, м;Верх, м;Высота, м;Толщина, мм\n'+'\n'.join(';'.join(str(b[k]) for k in ['number','bottom_m','top_m','height_m','thickness_mm']) for b in model.bands),encoding='utf-8-sig')
    groups=thickness_groups(model.bands)
    (Path(out)/'Участки толщины.csv').write_text('Участок;Первый пояс;Последний пояс;Низ, м;Верх, м;Толщина, мм\n'+'\n'.join(';'.join(str(g[k]) for k in ['index','first_belt','last_belt','bottom_m','top_m','thickness_mm']) for g in groups),encoding='utf-8-sig')
    if check:check.update(surface_count=len(groups),thickness_groups=groups,shared_boundaries=True)
    if check:(Path(out)/'Проверка экспорта.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf-8')

# REPORT_TEMPLATE and GUI are below; nothing is downloaded at runtime.

def segments(x,y,values,level=0):
    result=[]
    for j in range(len(y)-1):
        for i in range(len(x)-1):
            points=np.array([[x[i],y[j]],[x[i+1],y[j]],[x[i+1],y[j+1]],[x[i],y[j+1]]]);vs=np.array([values[j,i],values[j,i+1],values[j+1,i+1],values[j+1,i]])-level
            for tri in [(0,1,2),(0,2,3)]:
                hits=[]
                for a,b in zip(tri,tri[1:]+tri[:1]):
                    if vs[a]*vs[b]<0:hits.append(points[a]+vs[a]/(vs[a]-vs[b])*(points[b]-points[a]))
                if len(hits)==2:result.append(np.array(hits).tolist())
    return result

def area_centroid(x,y,values,sign,threshold):
    area=0.;moment=np.zeros(2)
    for j in range(len(y)-1):
        for i in range(len(x)-1):
            ps=np.array([[x[i],y[j]],[x[i+1],y[j]],[x[i+1],y[j+1]],[x[i],y[j+1]]]);vs=sign*np.array([values[j,i],values[j,i+1],values[j+1,i+1],values[j+1,i]])-threshold
            for tri in [(0,1,2),(0,2,3)]:
                poly=[]
                for a,b in zip(tri,tri[1:]+tri[:1]):
                    if vs[a]>=0:poly.append(ps[a])
                    if vs[a]*vs[b]<0:poly.append(ps[a]+vs[a]/(vs[a]-vs[b])*(ps[b]-ps[a]))
                if len(poly)>=3:
                    p=np.array(poly);q=np.roll(p,-1,axis=0);cross=p[:,0]*q[:,1]-q[:,0]*p[:,1];a=float(cross.sum()/2)
                    if abs(a)>1e-15:cent=np.sum((p+q)*cross[:,None],axis=0)/(6*a);area+=abs(a);moment+=abs(a)*cent
    return area,(moment/area).tolist() if area else None

def report_data(model):
    theta=np.linspace(0,2*np.pi,361);z=np.linspace(0,model.H,145);field=model.field(theta,z)
    S,Z=np.meshgrid(model.theta*model.R,model.z);points=np.column_stack([np.broadcast_to(np.degrees(model.theta),S.shape).ravel(),Z.ravel(),model.field(model.theta,model.z).ravel()]).tolist()
    dents=[]
    for d in model.defects:
        # Show an axis-aligned rectangle, fixed in the developed coordinates.
        s=np.linspace(d.sc+d.xx[0]-d.xp,d.sc+d.xx[-1]-d.xp,81);zz=np.linspace(max(0,d.zc+d.yy[0]-d.yp),min(model.H,d.zc+d.yy[-1]-d.yp),81)
        SS,ZZ=np.meshgrid(s,zz);local=d.evaluate(SS,ZZ);total=model.field(s/model.R,zz)
        contours=segments(s,zz,local,d.sign*model.threshold);area,center=area_centroid(s,zz,local,d.sign,model.threshold)
        sx=d.sc+d.x-d.xp;zy=d.zc+d.y-d.yp;PS,PZ=np.meshgrid(sx,zy);pv=model.field(sx/model.R,zy)
        points.extend(np.column_stack([((PS/model.R*180/np.pi)%360).ravel(),PZ.ravel(),pv.ravel()]).tolist())
        dents.append(dict(id=d.id,name=d.name,sc=d.sc,zc=d.zc,angle=d.sc/model.R*180/np.pi,depth=float(-np.min(d.values)),s=s.tolist(),z=zz.tolist(),grid=np.round(total,4).tolist(),contours=contours,center=center,area=area,local_peak_mm=float(d.values[d.peak_j,d.peak_i]),count=int(d.values.size)))
    minimum=min(float(field.min()),min(p[2] for p in points));maximum=max(float(field.max()),max(p[2] for p in points))
    for d in dents:minimum=min(minimum,float(np.min(d['grid'])));maximum=max(maximum,float(np.max(d['grid'])))
    return dict(radius=model.R,height=model.H,diameter=model.D,points=points,grid=np.round(field,4).tolist(),theta_count=len(theta),heights=z.tolist(),minimum=minimum,maximum=maximum,dents=dents,bands=model.bands,groups=thickness_groups(model.bands),threshold=model.threshold,point_error=model.point_error)

def report_write(path,model):
    data=report_data(model)
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    Path(path).write_text(REPORT_TEMPLATE.replace('__DATA__',payload),encoding='utf-8')

REPORT_TEMPLATE=r'''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Геометрия стенки резервуара</title>
<style>
:root{color-scheme:light dark;--bg:light-dark(#fff,#1e2024);--fg:light-dark(#20252b,#edf0f4);--line:light-dark(#d5dbe1,#50565d)}
body{background:var(--bg);color:var(--fg);font:15px 'Segoe UI',Arial,sans-serif;max-width:1200px;margin:28px auto;padding:0 22px}
h1{font-size:24px;font-weight:500}h2{font-size:17px;font-weight:500;margin:20px 0 7px}p{line-height:1.5}.views{display:grid;grid-template-columns:1fr 1fr;gap:18px}.wide{grid-column:1/-1}canvas{display:block;width:100%;height:350px}label{display:inline-flex;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 20px 10px 0}input{width:180px}small{display:block;line-height:1.5;color:var(--fg)}table{border-collapse:collapse;margin:16px 0}th,td{padding:7px 18px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}button{padding:8px 14px;cursor:pointer}@media(max-width:700px){.views{grid-template-columns:1fr}}@media print{label,button{display:none}body{color:#20252b;background:#fff}.views{grid-template-columns:1fr 1fr}section{break-inside:avoid}canvas{height:300px}}
</style>
<h1>Восстановленная геометрия стенки резервуара</h1><p id="summary"></p>
<label>Усиление отклонений <b id="amplabel">20×</b><input id="amp" type="range" min="1" max="30" value="20"></label>
<label>Поворот 3D <b id="turnlabel">25°</b><input id="turn" type="range" min="0" max="360" value="25"></label>
<button onclick="window.print()">Печать / PDF</button>
<div class="views" id="views"><section><h2>1. Точки · суммарное Δr, мм</h2><canvas id="points"></canvas></section><section><h2>2. Поверхность · суммарное Δr, мм</h2><canvas id="surface"></canvas></section><section class="wide"><h2>3. Развёртка · контуры и привязка локальных дефектов</h2><canvas id="unfold"></canvas></section></div>
<canvas id="legend" style="height:64px"></canvas>
<p>Цвет — модуль суммарного Δr. ○ внутрь, ● наружу; + наружу / − внутрь. Сплошная линия — Δr = 0. P — самая глубокая измеренная точка, C — центр площади выделенного контура. Усиление действует только на 3D-просмотр.</p>
<p id="threshold"></p><h2>Пояса стенки</h2><div id="bands"></div><h2>Участки поверхности для задания толщины</h2><div id="groups"></div>
<p>Соседние пояса одинаковой толщины объединены в одну поверхность. Все участки входят в одну связную оболочку с общими рёбрами. Объёмная толщина не добавлена: оболочечные свойства назначаются соответствующим участкам в расчётной модели. Радиальные отклонения измеряются в направлении от оси резервуара.</p>
<script>
(()=>{const D=__DATA__,amp=document.getElementById('amp'),turn=document.getElementById('turn'),views=document.getElementById('views');
 document.getElementById('summary').textContent=`D = ${D.diameter} м · H = ${D.height} м · ${D.points.length} точек · ${D.dents.length} локальных дефектов`;
 document.getElementById('threshold').textContent=`Контур локального дефекта выделен по собственному отклонению |δлок| = ${D.threshold} мм. Это порог обработки, не оценка точности измерений.`;
 const colors=[[0,0,255],[0,128,255],[0,255,255],[0,255,128],[0,255,0],[128,255,0],[255,255,0],[255,128,0],[255,0,0]],max=Math.max(Math.abs(D.minimum),Math.abs(D.maximum),1e-10);
 const color=v=>{const a=Math.min(1,Math.abs(v)/max)*8,k=Math.min(7,Math.floor(a)),f=a-k;return `rgb(${colors[k].map((v,i)=>Math.round(v+f*(colors[k+1][i]-v))).join(',')})`};
 for(const d of D.dents){const sec=document.createElement('section'),title=document.createElement('h2'),desc=document.createElement('small'),c=document.createElement('canvas');title.textContent=`${d.id+3}. ${d.name}`;desc.textContent=`P${d.id}: s = ${d.sc.toFixed(2)} м · φ = ${d.angle.toFixed(2)}° · Z = ${d.zc.toFixed(2)} м · δлок = ${d.local_peak_mm.toFixed(2)} мм · ${d.count} точек`;c.id='dent'+d.id;sec.append(title,desc,c);views.append(sec);}
 const bandtable=document.createElement('table');bandtable.innerHTML='<tr><th>Пояс</th><th>Низ, м</th><th>Верх, м</th><th>Толщина, мм</th></tr>'+D.bands.map(b=>`<tr><td>${b.number}</td><td>${b.bottom_m.toFixed(3)}</td><td>${b.top_m.toFixed(3)}</td><td>${b.thickness_mm.toFixed(3)}</td></tr>`).join('');document.getElementById('bands').append(bandtable);
 const grouptable=document.createElement('table');grouptable.innerHTML='<tr><th>Поверхность</th><th>Пояса</th><th>Низ, м</th><th>Верх, м</th><th>Толщина, мм</th></tr>'+D.groups.map(g=>`<tr><td>${g.index}</td><td>${g.first_belt}–${g.last_belt}</td><td>${g.bottom_m.toFixed(3)}</td><td>${g.top_m.toFixed(3)}</td><td>${g.thickness_mm.toFixed(3)}</td></tr>`).join('');document.getElementById('groups').append(grouptable);
 function setup(id,height=350){const c=document.getElementById(id),w=c.clientWidth,ratio=devicePixelRatio||1;c.width=w*ratio;c.height=height*ratio;const ctx=c.getContext('2d');ctx.scale(ratio,ratio);return {ctx,w,h:height};}
 function path(ctx,pts,stroke){if(!pts.length)return;ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(...pts[0].slice(0,2));for(const p of pts.slice(1))ctx.lineTo(...p.slice(0,2));ctx.stroke();}
 function zero(x,y,g,level=0){const out=[];for(let j=0;j<y.length-1;j++)for(let i=0;i<x.length-1;i++){const p=[[x[i],y[j]],[x[i+1],y[j]],[x[i+1],y[j+1]],[x[i],y[j+1]]],v=[g[j][i],g[j][i+1],g[j+1][i+1],g[j+1][i]].map(q=>q-level);for(const tri of [[0,1,2],[0,2,3]]){const hits=[];for(let e=0;e<3;e++){const a=tri[e],b=tri[(e+1)%3];if(v[a]*v[b]<0){const f=v[a]/(v[a]-v[b]);hits.push(p[a].map((q,k)=>q+f*(p[b][k]-q)));}}if(hits.length===2)out.push(hits);}}return out;}
 function project(w,h){const a=+turn.value*Math.PI/180,scale=Math.min((w-38)/(2*D.radius+max*amp.value/500+2),(h-38)/(D.height*.88+2*D.radius*.38+2));return (t,z,dr)=>{const r=D.radius+dr*amp.value/1000,x=r*Math.cos(t+a),y=r*Math.sin(t+a);return [w/2+x*scale,h/2+(y*.38-(z-D.height/2)*.88)*scale,y*.88+(z-D.height/2)*.38]};}
 function points(fg,line){const {ctx,w,h}=setup('points'),p=project(w,h),n=D.theta_count;for(let j=0;j<D.heights.length;j+=12)path(ctx,D.grid[j].map((v,i)=>p(i*2*Math.PI/(n-1),D.heights[j],v)),line);for(let i=0;i<n-1;i+=10)path(ctx,D.grid.map((r,j)=>p(i*2*Math.PI/(n-1),D.heights[j],r[i])),line);path(ctx,D.grid.map((r,j)=>p(0,D.heights[j],r[0])),fg);const sorted=D.points.map(v=>({v,q:p(v[0]*Math.PI/180,v[1],v[2])})).sort((a,b)=>a.q[2]-b.q[2]);for(const {v,q} of sorted){ctx.beginPath();ctx.arc(q[0],q[1],3,0,2*Math.PI);if(v[2]<-1e-8){ctx.strokeStyle=color(v[2]);ctx.lineWidth=1.1;ctx.stroke();}else{ctx.fillStyle=color(v[2]);ctx.fill();}}ctx.fillStyle=fg;ctx.font='12px Segoe UI';const a=p(0,D.height,D.grid.at(-1)[0]);ctx.fillText('№1',Math.max(6,Math.min(w-30,a[0])),Math.max(14,a[1]-8));}
 function surface(fg){const {ctx,w,h}=setup('surface'),p=project(w,h),cols=D.theta_count,vs=D.grid.map((r,j)=>r.map((v,i)=>p(i*2*Math.PI/(cols-1),D.heights[j],v))),faces=[];for(let j=0;j<vs.length-1;j++)for(let i=0;i<cols-1;i++){const q=[vs[j][i],vs[j][i+1],vs[j+1][i+1],vs[j+1][i]];faces.push({q,d:q.reduce((s,p)=>s+p[2],0)/4,v:(D.grid[j][i]+D.grid[j][i+1]+D.grid[j+1][i]+D.grid[j+1][i+1])/4,j,i});}faces.sort((a,b)=>a.d-b.d);for(const f of faces){ctx.fillStyle=color(f.v);ctx.beginPath();ctx.moveTo(...f.q[0].slice(0,2));for(const q of f.q.slice(1))ctx.lineTo(...q.slice(0,2));ctx.closePath();ctx.fill();ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=.4;ctx.stroke();const t=[f.i*2*Math.PI/(cols-1),(f.i+1)*2*Math.PI/(cols-1)],z=[D.heights[f.j],D.heights[f.j+1]],g=[[D.grid[f.j][f.i],D.grid[f.j][f.i+1]],[D.grid[f.j+1][f.i],D.grid[f.j+1][f.i+1]]];for(const pair of zero(t,z,g))path(ctx,pair.map(v=>p(v[0],v[1],0)),fg);}path(ctx,vs[0],fg);path(ctx,vs.at(-1),fg);}
 function flat(id,xs,ys,g,fg,line,local=null){const {ctx,w,h}=setup(id),left=64,right=w-16,top=22,bottom=h-53,x0=xs[0],x1=xs.at(-1),y0=ys[0],y1=ys.at(-1);let sx=(right-left)/(x1-x0),sy=(bottom-top)/(y1-y0),offx=0,offy=0;if(local){sx=sy=Math.min(sx,sy);offx=((right-left)-(x1-x0)*sx)/2;offy=((bottom-top)-(y1-y0)*sy)/2;}const x=s=>left+offx+(s-x0)*sx,y=z=>bottom-offy-(z-y0)*sy;
  for(let j=0;j<ys.length-1;j++)for(let i=0;i<xs.length-1;i++){ctx.fillStyle=color((g[j][i]+g[j][i+1]+g[j+1][i]+g[j+1][i+1])/4);ctx.fillRect(x(xs[i]),y(ys[j+1]),(xs[i+1]-xs[i])*sx+.3,(ys[j+1]-ys[j])*sy+.3);}
  const contours=zero(xs,ys,g),bg=getComputedStyle(document.body).backgroundColor;
  function label(text,s,z){ctx.font='14px Segoe UI';ctx.textAlign='center';ctx.strokeStyle=bg;ctx.lineWidth=3;ctx.strokeText(text,x(s),y(z));ctx.fillStyle=fg;ctx.fillText(text,x(s),y(z));}
  function at(s,z){const a=(s-x0)/(x1-x0)*(xs.length-1),b=(z-y0)/(y1-y0)*(ys.length-1);if(a<0||b<0||a>xs.length-1||b>ys.length-1)return null;const i=Math.min(xs.length-2,Math.floor(a)),j=Math.min(ys.length-2,Math.floor(b)),u=a-i,v=b-j;return (1-v)*((1-u)*g[j][i]+u*g[j][i+1])+v*((1-u)*g[j+1][i]+u*g[j+1][i+1]);}
  const placed=[];for(const [a,b] of contours){path(ctx,[[x(a[0]),y(a[1])],[x(b[0]),y(b[1])]],fg);const px=(x(a[0])+x(b[0]))/2,py=(y(a[1])+y(b[1]))/2;if(placed.some(v=>Math.hypot(px-v[0],py-v[1])<65))continue;const dx=x(b[0])-x(a[0]),dy=y(b[1])-y(a[1]),len=Math.hypot(dx,dy);if(len<1e-8)continue;const nx=-dy/len*13,ny=dx/len*13,s=(a[0]+b[0])/2,z=(a[1]+b[1])/2,va=at(s+nx/sx,z-ny/sy),vb=at(s-nx/sx,z+ny/sy);if(va===null||vb===null||va*vb>=0)continue;label(va>0?'+':'−',s+nx/sx,z-ny/sy);label(vb>0?'+':'−',s-nx/sx,z+ny/sy);placed.push([px,py]);}
  for(const d of local?[local]:D.dents){ctx.setLineDash([4,3]);for(const pair of d.contours){let p=pair.map(v=>[...v]);if(!local){const center=(p[0][0]+p[1][0])/2,shift=Math.floor(center/(2*Math.PI*D.radius))*2*Math.PI*D.radius;p=p.map(v=>[v[0]-shift,v[1]]);}if(p.every(v=>v[0]>=x0&&v[0]<=x1))path(ctx,p.map(v=>[x(v[0]),y(v[1])]),fg);}ctx.setLineDash([]);if(d.sc>=x0&&d.sc<=x1)label('P'+d.id,d.sc,d.zc);if(d.center){let s=d.center[0];if(!local)s=(s%(2*Math.PI*D.radius)+2*Math.PI*D.radius)%(2*Math.PI*D.radius);if(s>=x0&&s<=x1)label('C'+d.id,s,d.center[1]+22/sy);}}
  ctx.strokeStyle=line;ctx.lineWidth=1;ctx.strokeRect(x(x0),y(y1),x(x1)-x(x0),y(y0)-y(y1));ctx.fillStyle=fg;ctx.font='12px Segoe UI';ctx.textAlign='center';for(let i=0;i<4;i++){const s=x0+(x1-x0)*i/3;ctx.fillText(s.toFixed(local?2:1),x(s),y(y0)+20);}ctx.fillText('s от образующей №1, м',(x(x0)+x(x1))/2,h-9);ctx.textAlign='right';for(let i=0;i<4;i++){const z=y0+(y1-y0)*i/3;ctx.fillText(z.toFixed(local?2:1),x(x0)-8,y(z)+4);}ctx.fillText('Z, м',x(x0)-8,15);ctx.textAlign='start';
 }
 function legend(fg){const {ctx,w}=setup('legend',64),left=30,right=w-30,lo=Math.min(D.minimum,0),hi=Math.max(D.maximum,0);for(let i=0;i<512;i++){ctx.fillStyle=color(lo+(hi-lo)*i/511);ctx.fillRect(left+(right-left)*i/512,10,(right-left)/512+.3,16);}ctx.fillStyle=fg;ctx.font='12px Segoe UI';if(hi-lo<1e-9){ctx.textAlign='center';ctx.fillText('0 мм',(left+right)/2,48);return;}for(const [v,text,align] of [[lo,lo.toFixed(2),'left'],[0,'0','center'],[hi,(hi>0?'+':'')+hi.toFixed(2),'right']]){const x=left+(v-lo)/(hi-lo)*(right-left);ctx.strokeStyle=fg;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,6);ctx.lineTo(x,32);ctx.stroke();ctx.textAlign=align;ctx.fillText(text+' мм',x,48);}}
 function draw(){const fg=getComputedStyle(document.body).color,line=getComputedStyle(document.querySelector('td')).borderBottomColor;document.getElementById('amplabel').textContent=amp.value+'×';document.getElementById('turnlabel').textContent=turn.value+'°';points(fg,line);surface(fg);flat('unfold',Array.from({length:D.theta_count},(_,i)=>i*2*Math.PI*D.radius/(D.theta_count-1)),D.heights,D.grid,fg,line);for(const d of D.dents)flat('dent'+d.id,d.s,d.z,d.grid,fg,line,d);legend(fg);}
 let queued=false;function schedule(){if(!queued){queued=true;requestAnimationFrame(()=>{queued=false;draw()});}}amp.addEventListener('input',schedule);turn.addEventListener('input',schedule);new ResizeObserver(schedule).observe(document.body);matchMedia('(prefers-color-scheme:dark)').addEventListener('change',schedule);draw();
})();
</script></html>'''
