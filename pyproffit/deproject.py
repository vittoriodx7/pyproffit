from astropy.cosmology import WMAP9 as cosmo
import numpy as np
import time
from scipy.special import gamma
import matplotlib.pyplot as plt
#plt.switch_backend('Agg')
from scipy.interpolate import interp1d

Mpc = 3.0856776e+24 #cm
mu_e = 1.1738 #proton to electron ratio in pristine fully ionized gas
kpc = 3.0856776e+21 #cm
mup = 0.6125 #mean molecular weight
msun = 1.9891e33 #g
mh = 1.66053904e-24 #proton mass in g
nhc = 1./0.8337

# Function to calculate a linear operator transforming parameter vector into predicted model counts

def calc_linear_operator(rad,sourcereg,pars,area,expo,psf):
    # Select values in the source region
    rfit=rad[sourcereg]
    npt=len(rfit)
    npars=len(pars[:,0])
    areamul=np.tile(area[0:npt],npars).reshape(npars,npt)
    expomul=np.tile(expo[0:npt],npars).reshape(npars,npt)
    spsf=psf[0:npt,0:npt]
    
    # Compute linear combination of basis functions in the source region
    beta=np.repeat(pars[:,0],npt).reshape(npars,npt)
    rc=np.repeat(pars[:,1],npt).reshape(npars,npt)
    base=1.+np.power(rfit/rc,2)
    expon=-3.*beta+0.5
    func_base=np.power(base,expon)
    
    # Predict number of counts per annulus and convolve with PSF
    Ktrue=func_base*areamul*expomul
    Kconv=np.dot(spsf,Ktrue.T)
    
    # Recast into full matrix and add column for background
    nptot=len(rad)
    Ktot=np.zeros((nptot,npars+1))
    Ktot[0:npt,0:npars]=Kconv
    Ktot[:,npars]=area*expo
    return Ktot

# Function to create the list of parameters for the basis functions
nsh=4. # number of basis functions to set

def list_params(rad,sourcereg,nrc=None,nbetas=6):
    rfit=rad[sourcereg]
    npfit=len(rfit)
    if nrc is None:
        nrc = int(npfit/nsh)
    allrc=np.logspace(np.log10(rfit[2]),np.log10(rfit[npfit-1]/2.),nrc)
    #allbetas=np.linspace(0.4,3.,6)
    allbetas = np.linspace(0.6, 3., nbetas)
    nrc=len(allrc)
    nbetas=len(allbetas)
    rc=allrc.repeat(nbetas)
    betas=np.tile(allbetas,nrc)
    ptot=np.empty((nrc*nbetas,2))
    ptot[:,0]=betas
    ptot[:,1]=rc
    return ptot

# Function to create a linear operator transforming parameters into surface brightness

def calc_sb_operator(rad,sourcereg,pars):
    # Select values in the source region
    rfit=rad[sourcereg]
    npt=len(rfit)
    npars=len(pars[:,0])
    
    # Compute linear combination of basis functions in the source region
    beta=np.repeat(pars[:,0],npt).reshape(npars,npt)
    rc=np.repeat(pars[:,1],npt).reshape(npars,npt)
    base=1.+np.power(rfit/rc,2)
    expon=-3.*beta+0.5
    func_base=np.power(base,expon)
    
    # Recast into full matrix and add column for background
    nptot=len(rad)
    Ktot=np.zeros((nptot,npars+1))
    Ktot[0:npt,0:npars]=func_base.T
    Ktot[:,npars]=1.0
    return Ktot

def calc_int_operator(a, b, pars):
    # Select values in the source region
    npars = len(pars[:, 0])
    rads = np.array([a, b])
    npt = 2

    # Compute linear combination of basis functions in the source region
    beta = np.repeat(pars[:, 0], npt).reshape(npars, npt)
    rc = np.repeat(pars[:, 1], npt).reshape(npars, npt)
    base = 1. + np.power(rads / rc, 2)
    expon = -3. * beta + 1.5
    func_base = 2. * np.pi * np.power(base, expon) / (3 - 6 * beta) * rc**2

    # Recast into full matrix and add column for background
    Kint = np.zeros((npt, npars + 1))
    Kint[0:npt, 0:npars] = func_base.T
    Kint[:, npars] = 0.0
    return Kint


def list_params_density(rad,sourcereg,z,nrc=None,nbetas=6):
    rfit=rad[sourcereg]
    npfit=len(rfit)
    kpcp=cosmo.kpc_proper_per_arcmin(z).value
    if nrc is None:
        nrc = int(npfit/nsh)
    allrc=np.logspace(np.log10(rfit[2]),np.log10(rfit[npfit-1]/2.),nrc)*kpcp
    #allbetas=np.linspace(0.5,3.,6)
    allbetas = np.linspace(0.6, 3., nbetas)
    nrc=len(allrc)
    nbetas=len(allbetas)
    rc=allrc.repeat(nbetas)
    betas=np.tile(allbetas,nrc)
    ptot=np.empty((nrc*nbetas,2))
    ptot[:,0]=betas
    ptot[:,1]=rc
    return ptot

# Linear operator to transform parameters into density

def calc_density_operator(rad,sourcereg,pars,z):
    # Select values in the source region
    kpcp=cosmo.kpc_proper_per_arcmin(z).value
    rfit=rad[sourcereg]*kpcp
    npt=len(rfit)
    npars=len(pars[:,0])
    
    # Compute linear combination of basis functions in the source region
    beta=np.repeat(pars[:,0],npt).reshape(npars,npt)
    rc=np.repeat(pars[:,1],npt).reshape(npars,npt)
    base=1.+np.power(rfit/rc,2)
    expon=-3.*beta
    func_base=np.power(base,expon)
    cfact=gamma(3*beta)/gamma(3*beta-0.5)/np.sqrt(np.pi)/rc
    fng=func_base*cfact
    
    # Recast into full matrix and add column for background
    nptot=len(rad)
    Ktot=np.zeros((nptot,npars+1))
    Ktot[0:npt,0:npars]=fng.T
    Ktot[:,npars]=0.0
    return Ktot


def Deproject_Multiscale(deproj,bkglim=None,nmcmc=1000,back=None,samplefile=None,nrc=None,nbetas=6,use_stan=False):
    prof = deproj.profile
    sb = prof.profile
    rad = prof.bins
    erad = prof.ebins
    counts = prof.counts
    area = prof.area
    exposure = prof.effexp
    bkgcounts = prof.bkgcounts

    # Define maximum radius for source deprojection, assuming we have only background for r>bkglim
    if bkglim is None:
        bkglim=np.max(rad+erad)
        deproj.bkglim = bkglim
        if back is None:
            back = sb[len(sb) - 1]
    else:
        deproj.bkglim = bkglim
        backreg = np.where(rad>bkglim)
        if back is None:
            back = np.mean(sb[backreg])

    # Set source region
    sourcereg = np.where(rad < bkglim)
    nptfit = len(sb[sourcereg])

    # Set vector with list of parameters
    pars = list_params(rad, sourcereg, nrc, nbetas)
    npt = len(pars)

    if prof.psfmat is not None:
        psfmat = np.transpose(prof.psfmat)
    else:
        psfmat = np.eye(prof.nbin)

    # Compute linear combination kernel
    K = calc_linear_operator(rad, sourcereg, pars, area, exposure, psfmat)
    if np.isnan(sb[0]) or sb[0] <= 0:
        testval = -10.
    else:
        testval = np.log(sb[0] / npt)
    if np.isnan(back) or back == 0:
        testbkg = -10.
    else:
        testbkg = np.log(back)
     
    
    if use_stan == False:
        import pymc3 as pm
        basic_model = pm.Model()


        with basic_model:
            # Priors for unknown model parameters
            coefs = pm.Normal('coefs', mu=testval, sd=20, shape=npt)
            bkgd = pm.Normal('bkg', mu=testbkg, sd=0.05, shape=1)
            ctot = pm.math.concatenate((coefs, bkgd), axis=0)

            # Expected value of outcome
            al = pm.math.exp(ctot)
            pred = pm.math.dot(K, al) + bkgcounts

            # Likelihood (sampling distribution) of observations
            Y_obs = pm.Poisson('counts', mu=pred, observed=counts)

        tinit = time.time()
        print('Running MCMC...')
        with basic_model:
            #tm = pm.find_MAP()
            #trace = pm.sample(nmcmc, start=tm)
            trace = pm.sample(nmcmc)
        print('Done.')
        tend = time.time()
        print(' Total computing time is: ', (tend - tinit) / 60., ' minutes')
        sampc = trace.get_values('coefs')
        sampb = trace.get_values('bkg')
        samples = np.append(sampc, sampb, axis=1)      
    else:
        import pystan
        import stan_utility as su
        
        if not os.path.isfile('mybeta_GP.stan'): # write and compile code if not already present
            code='''
            data {
            int<lower=0> N;
            int<lower=0> M;
            int cts_tot[N];
            vector[N] cts_back;
            matrix[N,M] K;
            vector[M] norm0;
            }

            parameters {
            vector[M] log_norm;
            }

            transformed parameters{
            vector[M] norm = exp(log_norm);
            }

            model {
            log_norm ~ normal(norm0,10);

            cts_tot ~ poisson(K * norm + cts_back);
            }'''
            f=open('mybeta_GP.stan','w')
            print(code,file=f)
            f.close()
            sm = su.compile_model('mybeta_gauss.stan',model_name='model_GP')
            
        depth=10
        datas=dict(K=K, cts_tot=counts.astype(int), cts_back=bkgcounts, N=K.shape[0],M=K.shape[1], norm0=np.append(testval,testbkg))
        tinit = time.time()
        print('Running MCMC...')
        fit = sm.sampling(data=datas,chains=1,iter=nmcmc,thin=1,n_jobs=1, control={'max_treedepth':depth})
        print('Done.')
        tend = time.time()
        print(' Total computing time is: ', (tend - tinit) / 60., ' minutes')            
        chain = fit.extract()
        samples=chain['log_norm']           
            
            
            
    # Get chains and save them to file

    if samplefile is not  None:
        np.savetxt(samplefile, samples)

    # Compute output deconvolved brightness profile
    Ksb = calc_sb_operator(rad, sourcereg, pars)
    allsb = np.dot(Ksb, np.exp(samples.T))
    bfit = np.median(np.exp(samples[:, npt]))
    pmc = np.median(allsb, axis=1)
    pmcl = np.percentile(allsb, 50. - 68.3 / 2., axis=1)
    pmch = np.percentile(allsb, 50. + 68.3 / 2., axis=1)

    deproj.samples = samples
    deproj.sb = pmc
    deproj.sb_lo = pmcl
    deproj.sb_hi = pmch
    deproj.bkg = bfit



class MyDeprojVol:
    def __init__(self, radin, radot):
        self.radin=radin
        self.radot=radot
        self.help=''

    def deproj_vol(self):
        ###############volume=deproj_vol(radin,radot)
        ri=np.copy(self.radin)
        ro=np.copy(self.radot)

        diftot=0
        for i in range(1,len(ri)):
            dif=abs(ri[i]-ro[i-1])/ro[i-1]*100.
            diftot=diftot+dif
            ro[i-1]=ri[i]

        if abs(diftot) > 0.1:
            print(' DEPROJ_VOL: WARNING - abs(ri(i)-ro(i-1)) differs by',diftot,' percent')
            print(' DEPROJ_VOL: Fixing up radii ... ')
            for i in range(1,len(ri)-1):
                dif=abs(ri[i]-ro[i-1])/ro[i-1]*100.
                diftot=diftot+dif
        nbin=len(ro)
        volconst=4./3.*np.pi
        volmat=np.zeros((nbin, nbin))

        for iring in list(reversed(range(0,nbin))):
            volmat[iring,iring]=volconst * ro[iring]**3 * (1.-(ri[iring]/ro[iring])**2.)**1.5
            for ishell in list(reversed(range(iring+1,nbin))):
                f1=(1.-(ri[iring]/ro[ishell])**2.)**1.5 - (1.-(ro[iring]/ro[ishell])**2.)**1.5
                f2=(1.-(ri[iring]/ri[ishell])**2.)**1.5 - (1.-(ro[iring]/ri[ishell])**2.)**1.5
                volmat[ishell,iring]=volconst * (f1*ro[ishell]**3 - f2*ri[ishell]**3)

                if volmat[ishell,iring] < 0.0:
                    exit()

        volume2=np.copy(volmat)
        return volume2

def medsmooth(prof):
    width=5
    nbin=len(prof)
    xx=np.empty((nbin,width))
    xx[:,0]=np.roll(prof,2)
    xx[:,1]=np.roll(prof,1)
    xx[:,2]=prof
    xx[:,3]=np.roll(prof,-1)
    xx[:,4]=np.roll(prof,-2)
    smoothed=np.median(xx,axis=1)
    smoothed[1]=np.median(xx[1,1:width])
    smoothed[nbin-2]=np.median(xx[nbin-2,0:width-1])
    Y0=3.*prof[0]-2.*prof[1]
    xx=np.array([Y0,prof[0],prof[1]])
    smoothed[0]=np.median(xx)
    Y0=3.*prof[nbin-1]-2.*prof[nbin-2]
    xx=np.array([Y0,prof[nbin-2],prof[nbin-1]])
    smoothed[nbin-1]=np.median(xx)
    return  smoothed

def EdgeCorr(nbin,rin_cm,rout_cm,em0):
    # edge correction
    mrad = [rin_cm[nbin - 1], rout_cm[nbin - 1]]
    edge0 = (mrad[0] + mrad[1]) * mrad[0] * mrad[1] / rout_cm ** 3
    edge1 = 2. * rout_cm / mrad[1] + np.arccos(rout_cm / mrad[1])
    edge2 = rout_cm / mrad[1] * np.sqrt(1. - rout_cm ** 2 / mrad[1] ** 2)
    edget = edge0 * (-1. + 2. / np.pi * (edge1 - edge2))
    j = np.where(rin_cm != 0)
    edge0[j] = (mrad[0] + mrad[1]) * mrad[0] * mrad[1] / (rin_cm[j] + rout_cm[j]) / rin_cm[j] / rout_cm[j]
    edge1[j] = rout_cm[j] / rin_cm[j] * np.arccos(rin_cm[j] / mrad[1]) - np.arccos(rout_cm[j] / mrad[1])
    edge2[j] = rout_cm[j] / mrad[1] * (
                np.sqrt(1. - rin_cm[j] ** 2 / mrad[1] ** 2) - np.sqrt(1. - rout_cm[j] ** 2 / mrad[1] ** 2))
    edget[j] = edge0[j] * (1. - 2. / np.pi * (edge1[j] - edge2[j]) / (rout_cm[j] / rin_cm[j] - 1.))
    surf = (rout_cm ** 2 - rin_cm ** 2) / (rout_cm[nbin - 1] ** 2 - rin_cm[nbin - 1] ** 2)
    corr = edget * surf * em0[nbin-1] / em0.clip(min=1e-10)
    return corr

def OP(deproj,nmc=1000):
    # Standard onion peeling
    prof=deproj.profile
    nbin=prof.nbin
    rinam=prof.bins - prof.ebins
    routam=prof.bins + prof.ebins
    area=np.pi*(routam**2-rinam**2) # full area in arcmin^2

    # Projection volumes
    if deproj.z is not None and deproj.cf is not None:
        amin2kpc = cosmo.kpc_proper_per_arcmin(deproj.z).value
        rin_cm = (prof.bins - prof.ebins)*amin2kpc*Mpc/1e3
        rout_cm = (prof.bins + prof.ebins)*amin2kpc*Mpc/1e3
        x=MyDeprojVol(rin_cm,rout_cm)
        vol=np.transpose(x.deproj_vol())
        dlum=cosmo.luminosity_distance(deproj.z).value*Mpc
        K2em=4.*np.pi*1e14*dlum**2/(1+deproj.z)**2/nhc/deproj.cf

        # Projected emission measure profiles
        em0 = prof.profile * K2em * area
        e_em0 = prof.eprof * K2em * area
        corr = EdgeCorr(nbin, rin_cm, rout_cm, em0)
    else:
        x=MyDeprojVol(rinam,routam)
        vol=np.transpose(x.deproj_vol()).T
        em0 = prof.profile * area
        e_em0 = prof.profile * area
        corr = EdgeCorr(nbin,rinam,routam)

    # Deproject and propagate error using Monte Carlo
    emres = np.repeat(e_em0,nmc).reshape(nbin,nmc) * np.random.randn(nbin,nmc) + np.repeat(em0,nmc).reshape(nbin,nmc)
    ct = np.repeat(corr,nmc).reshape(nbin,nmc)
    allres = np.linalg.solve(vol, emres * (1. - ct))
    ev0 = np.std(allres,axis=1)
    v0 = np.median(allres,axis=1)
    bsm = medsmooth(v0)

    deproj.sb = bsm
    deproj.sb_lo = bsm - ev0
    deproj.sb_hi = bsm + ev0

    deproj.dens = medsmooth(np.sign(bsm)*np.sqrt(np.abs(bsm)))
    edens = 0.5/np.sqrt(np.abs(bsm))*ev0
    deproj.dens_lo = deproj.dens - edens
    deproj.dens_hi = deproj.dens + edens


class Deproject:
    def __init__(self,z=None,profile=None,cf=None):
        self.profile = profile
        self.z = z
        self.samples = None
        self.cf = cf
        self.dens = None
        self.dens_lo = None
        self.dens_hi = None
        self.sb = None
        self.sb_lo = None
        self.sb_hi = None
        self.covmat = None
        self.bkg = None
        self.samples = None
        self.bkglim = None

    def Multiscale(self,nmcmc=1000,bkglim=None,back=None,samplefile=None):
        Deproject_Multiscale(self,bkglim=bkglim,back=back,nmcmc=nmcmc,samplefile=samplefile)

    def OnionPeeling(self,nmc=1000):
        OP(self,nmc)

    def PlotDensity(self,outfile=None):
        # Plot extracted profile
        if self.profile is None:
            print('Error: No profile extracted')
            return
        if self.dens is None:
            print('Error: No density profile extracted')
            return

        kpcp = cosmo.kpc_proper_per_arcmin(self.z).value
        rkpc = self.profile.bins * kpcp
        erkpc = self.profile.ebins * kpcp

        plt.clf()
        fig = plt.figure(figsize=(13, 10))
        ax_size = [0.14, 0.14,
                   0.83, 0.83]
        ax = fig.add_axes(ax_size)
        ax.minorticks_on()
        ax.tick_params(length=20, width=1, which='major', direction='in', right='on', top='on')
        ax.tick_params(length=10, width=1, which='minor', direction='in', right='on', top='on')
        for item in (ax.get_xticklabels() + ax.get_yticklabels()):
            item.set_fontsize(18)
        plt.xlabel('Radius [kpc]', fontsize=40)
        plt.ylabel('$n_{H}$ [cm$^{-3}$]', fontsize=40)
        plt.xscale('log')
        plt.yscale('log')
        plt.errorbar(rkpc, self.dens, xerr=erkpc, yerr=[self.dens-self.dens_lo,self.dens_hi-self.dens], fmt='o', color='black', elinewidth=2,
                     markersize=7, capsize=0,mec='black')
        plt.fill_between(rkpc,self.dens_lo,self.dens_hi,color='blue',alpha=0.5)
        if outfile is not None:
            plt.savefig(outfile)
            plt.close()
        else:
            plt.show(block=False)

    def Density(self):
        z = self.z
        cf = self.cf
        samples = self.samples
        prof = self.profile
        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)

        if z is not None and cf is not None:
            transf = 4. * (1. + z) ** 2 * (180. * 60.) ** 2 / np.pi / 1e-14 / nhc / Mpc * 1e3
            pardens = list_params_density(rad, sourcereg, z)
            Kdens = calc_density_operator(rad, sourcereg, pardens, z)
            alldens = np.sqrt(np.dot(Kdens, np.exp(samples.T)) / cf * transf)  # [0:nptfit, :]
            covmat = np.cov(alldens)
            self.covmat = covmat
            pmcd = np.median(alldens, axis=1)
            pmcdl = np.percentile(alldens, 50. - 68.3 / 2., axis=1)
            pmcdh = np.percentile(alldens, 50. + 68.3 / 2., axis=1)
            self.dens = pmcd
            self.dens_lo = pmcdl
            self.dens_hi = pmcdh
        else:
            print('No redshift and/or conversion factor, nothing to do')

    def PlotSB(self,outfile=None):
        if self.profile is None:
            print('Error: No profile extracted')
            return
        if self.sb is None:
            print('Error: No reconstruction available')
            return
        plt.clf()
        fig = plt.figure(figsize=(13, 10))
        ax_size = [0.14, 0.14,
                   0.83, 0.83]
        ax = fig.add_axes(ax_size)
        ax.minorticks_on()
        ax.tick_params(length=20, width=1, which='major', direction='in', right='on', top='on')
        ax.tick_params(length=10, width=1, which='minor', direction='in', right='on', top='on')
        for item in (ax.get_xticklabels() + ax.get_yticklabels()):
            item.set_fontsize(18)
        plt.xlabel('Radius [arcmin]', fontsize=40)
        plt.ylabel('SB [counts s$^{-1}$ arcmin$^{-2}$]', fontsize=40)
        plt.xscale('log')
        plt.yscale('log')
        plt.errorbar(self.profile.bins, self.sb, xerr=self.profile.ebins, yerr=[self.sb-self.sb_lo,self.sb_hi-self.sb], fmt='o', color='blue', elinewidth=2,
                     markersize=7, capsize=0,mec='blue',label='Reconstruction')
        plt.fill_between(self.profile.bins,self.sb_lo,self.sb_hi,color='blue',alpha=0.5)
        plt.errorbar(self.profile.bins, self.profile.profile, xerr=self.profile.ebins, yerr=self.profile.eprof, fmt='o', color='black', elinewidth=2,
                     markersize=7, capsize=0,mec='black',label='Data')
        if outfile is not None:
            plt.savefig(outfile)
            plt.close()
        else:
            plt.show(block=False)


    def CountRate(self,a,b,plot=True,outfile=None):
        if self.samples is None:
            print('Error: no MCMC samples found')
            return
        # Set source region
        prof = self.profile
        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)

        # Avoid diverging profiles in the center by cutting to the innermost points, if necessary
        if a<prof.bins[0]/2.:
            a = prof.bins[0]/2.

        # Set vector with list of parameters
        pars = list_params(rad, sourcereg)
        Kint = calc_int_operator(a, b, pars)
        allint = np.dot(Kint, np.exp(self.samples.T))
        medint = np.median(allint[1, :] - allint[0, :])
        intlo = np.percentile(allint[1, :] - allint[0, :], 50. - 68.3 / 2.)
        inthi = np.percentile(allint[1, :] - allint[0, :], 50. + 68.3 / 2.)
        print('Reconstructed count rate: %g (%g , %g)' % (medint, intlo, inthi))
        if plot:
            plt.clf()
            fig = plt.figure(figsize=(13, 10))
            ax_size = [0.14, 0.12,
                       0.85, 0.85]
            ax = fig.add_axes(ax_size)
            ax.minorticks_on()
            ax.tick_params(length=20, width=1, which='major', direction='in', right='True', top='True')
            ax.tick_params(length=10, width=1, which='minor', direction='in', right='True', top='True')
            for item in (ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontsize(22)
            # plt.yscale('log')
            plt.hist(allint[1,:]-allint[0,:], bins=30)
            plt.xlabel('Count Rate [cts/s]', fontsize=40)
            plt.ylabel('Frequency', fontsize=40)
            if outfile is not None:
                plt.savefig(outfile)
                plt.close()
            else:
                plt.show(block=False)

        return  medint,intlo,inthi

    def Ncounts(self,plot=True,outfile=None):
        if self.samples is None:
            print('Error: no MCMC samples found')
            return
        # Set source region
        prof = self.profile
        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)
        area = prof.area
        exposure = prof.effexp

        if prof.psfmat is not None:
            psfmat = np.transpose(prof.psfmat)
        else:
            psfmat = np.eye(prof.nbin)

        # Set vector with list of parameters
        pars = list_params(rad, sourcereg)
        K = calc_linear_operator(rad, sourcereg, pars, area, exposure, psfmat)
        npars = len(pars[:, 0])
        K[:,npars] = 0.
        allnc = np.dot(K, np.exp(self.samples.T))
        ncv = np.sum(allnc, axis=0)
        pnc = np.median(ncv)
        pncl = np.percentile(ncv, 50. - 68.3 / 2.)
        pnch = np.percentile(ncv, 50. + 68.3 / 2.)
        print('Reconstructed counts: %g (%g , %g)' % (pnc, pncl, pnch))
        if plot:
            plt.clf()
            fig = plt.figure(figsize=(13, 10))
            ax_size = [0.14, 0.12,
                       0.85, 0.85]
            ax = fig.add_axes(ax_size)
            ax.minorticks_on()
            ax.tick_params(length=20, width=1, which='major', direction='in', right='True', top='True')
            ax.tick_params(length=10, width=1, which='minor', direction='in', right='True', top='True')
            for item in (ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontsize(22)
            # plt.yscale('log')
            plt.hist(ncv, bins=30)
            plt.xlabel('$N_{count}$', fontsize=40)
            plt.ylabel('Frequency', fontsize=40)
            if outfile is not None:
                plt.savefig(outfile)
                plt.close()
            else:
                plt.show(block=False)

        return  pnc,pncl,pnch


    # Compute Mgas within radius in kpc
    def Mgas(self,radius,plot=True,outfile=None):
        if self.samples is None or self.z is None or self.cf is None:
            print('Error: no gas density profile found')
            return
        prof = self.profile
        kpcp = cosmo.kpc_proper_per_arcmin(self.z).value
        rkpc = prof.bins * kpcp
        erkpc = prof.ebins * kpcp
        nhconv =  mh * mu_e * nhc * kpc ** 3 / msun  # Msun/kpc^3

        rad = prof.bins
        sourcereg = np.where(rad < self.bkglim)

        transf = 4. * (1. + self.z) ** 2 * (180. * 60.) ** 2 / np.pi / 1e-14 / nhc / Mpc * 1e3
        pardens = list_params_density(rad, sourcereg, self.z)
        Kdens = calc_density_operator(rad, sourcereg, pardens, self.z)

        # All gas density profiles
        alldens = np.sqrt(np.dot(Kdens, np.exp(self.samples.T)) / self.cf * transf)  # [0:nptfit, :]

        # Matrix containing integration volumes
        volmat = np.repeat(4. * np.pi * rkpc ** 2 * 2. * erkpc, alldens.shape[1]).reshape(len(prof.bins),alldens.shape[1])

        # Compute Mgas profile as cumulative sum over the volume
        mgas = np.cumsum(alldens * nhconv * volmat, axis=0)

        # Interpolate at the radius of interest
        f = interp1d(rkpc, mgas, axis=0)
        mgasdist = f(radius)
        mg, mgl, mgh = np.percentile(mgasdist,[50.,50.-68.3/2.,50.+68.3/2.])
        if plot:
            plt.clf()
            fig = plt.figure(figsize=(13, 10))
            ax_size = [0.14, 0.12,
                       0.85, 0.85]
            ax = fig.add_axes(ax_size)
            ax.minorticks_on()
            ax.tick_params(length=20, width=1, which='major', direction='in', right='True', top='True')
            ax.tick_params(length=10, width=1, which='minor', direction='in', right='True', top='True')
            for item in (ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontsize(22)
            # plt.yscale('log')
            plt.hist(mgasdist, bins=30)
            plt.xlabel('$M_{gas} [M_\odot]$', fontsize=40)
            plt.ylabel('Frequency', fontsize=40)
            if outfile is not None:
                plt.savefig(outfile)
                plt.close()
            else:
                plt.show(block=False)

        return mg,mgl,mgh

    def Reload(self,samplefile,bkglim=None):
        # Reload the output of a previous PyMC3 run
        samples = np.loadtxt(samplefile)
        self.samples = samples
        if self.profile is None:
            print('Error: no profile provided')
            return

        prof = self.profile
        sb = prof.profile
        rad = prof.bins
        erad = prof.ebins

        if bkglim is not None:
            self.bkglim = bkglim
        else:
            if self.bkglim is None:
                bkglim = np.max(rad + erad)
                self.bkglim = bkglim

        # Set source region
        sourcereg = np.where(rad < bkglim)

        # Set vector with list of parameters
        pars = list_params(rad, sourcereg)
        npt = len(pars)
        # Compute output deconvolved brightness profile
        Ksb = calc_sb_operator(rad, sourcereg, pars)
        allsb = np.dot(Ksb, np.exp(samples.T))
        bfit = np.median(np.exp(samples[:, npt]))
        pmc = np.median(allsb, axis=1)
        pmcl = np.percentile(allsb, 50. - 68.3 / 2., axis=1)
        pmch = np.percentile(allsb, 50. + 68.3 / 2., axis=1)

        self.sb = pmc
        self.sb_lo = pmcl
        self.sb_hi = pmch
        self.bkg = bfit

    def CSB(self,rin=40.,rout=400.,plot=True,outfile=None):
        if self.samples is None or self.z is None:
            print('Error: no profile reconstruction found')
            return
        prof = self.profile
        kpcp = cosmo.kpc_proper_per_arcmin(self.z).value

        sourcereg = np.where(prof.bins < self.bkglim)

        # Set vector with list of parameters
        pars = list_params(prof.bins, sourcereg)
        Kin = calc_int_operator(prof.bins[0]/2., rin/kpcp, pars)
        allvin = np.dot(Kin, np.exp(self.samples.T))
        Kout = calc_int_operator(prof.bins[0]/2., rout/kpcp, pars)
        allvout = np.dot(Kout, np.exp(self.samples.T))
        medcsb = np.median((allvin[1, :] - allvin[0, :]) / (allvout[1, :] - allvout[0, :]))
        csblo = np.percentile((allvin[1, :] - allvin[0, :]) / (allvout[1, :] - allvout[0, :]), 50. - 68.3 / 2.)
        csbhi = np.percentile((allvin[1, :] - allvin[0, :]) / (allvout[1, :] - allvout[0, :]), 50. + 68.3 / 2.)
        print('Surface brightness concentration: %g (%g , %g)' % (medcsb, csblo, csbhi))

        if plot:
            plt.clf()
            fig = plt.figure(figsize=(13, 10))
            ax_size = [0.14, 0.12,
                       0.85, 0.85]
            ax = fig.add_axes(ax_size)
            ax.minorticks_on()
            ax.tick_params(length=20, width=1, which='major', direction='in', right='True', top='True')
            ax.tick_params(length=10, width=1, which='minor', direction='in', right='True', top='True')
            for item in (ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontsize(22)
            # plt.yscale('log')
            plt.hist((allvin[1, :] - allvin[0, :]) / (allvout[1, :] - allvout[0, :]), bins=30)
            plt.xlabel('$C_{SB}$', fontsize=40)
            plt.ylabel('Frequency', fontsize=40)
            if outfile is not None:
                plt.savefig(outfile)
                plt.close()
            else:
                plt.show(block=False)

        return  medcsb,csblo,csbhi





