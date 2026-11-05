"""Hand-written descriptions for well-known satellites.

The orbit numbers on the dashboard come from the TLE, and owner/type/launch
data comes from CelesTrak's SATCAT. This file only holds the text neither of
those can tell you. Satellites listed here show up under FEATURED in the
dropdown. Everything else is still trackable, just without a write-up.

To add one: copy an entry, change the NORAD id (the number in the dropdown),
and write the text yourself from a source you checked. `wiki` is the exact
English Wikipedia article title used to pull the image. Leave it out if there
is no good article, and the image panel will say so honestly.
"""

CATALOG = {
    25544: {
        'mission': 'International Space Station',
        'history': 'Assembly began in November 1998 and crews have lived aboard '
                   'continuously since November 2000. A partnership of NASA, '
                   'Roscosmos, JAXA, ESA and CSA.',
        'science': 'Microgravity physics, biology and materials research, human '
                   'adaptation to long spaceflight, AMS-02 particle physics.',
        'wiki': 'International_Space_Station',
    },
    20580: {
        'mission': 'Hubble Space Telescope',
        'history': 'Deployed from Space Shuttle Discovery in April 1990. '
                   'Serviced by astronauts five times, the last in 2009.',
        'science': 'Deep-field galaxy surveys, exoplanet atmospheres, the '
                   'expansion rate of the universe.',
        'wiki': 'Hubble_Space_Telescope',
    },
    48274: {
        'mission': 'Tiangong Space Station (Tianhe core module)',
        'history': 'Assembly in low Earth orbit began with the Tianhe core '
                   'module in April 2021.',
        'science': 'Fluid physics, space life science, combustion science and '
                   'microgravity materials work.',
        'wiki': 'Tiangong_space_station',
    },
    33591: {
        'mission': 'NOAA-19 polar-orbiting weather satellite',
        'history': 'Launched February 2009 into a sun-synchronous orbit as part '
                   'of the NOAA POES series.',
        'science': 'Atmospheric sounding, sea surface temperature, cloud '
                   'imagery. Broadcasts APT images an SDR can receive.',
        'wiki': 'NOAA-19',
    },
    # ---- Added from general knowledge. Skim these and correct anything wrong. ----
    27386: {
        'mission': 'Envisat (ESA Earth observation satellite)',
        'history': 'Launched by ESA in March 2002. Contact was lost in April 2012. '
                   'At roughly 8 tonnes it was among the largest civilian Earth '
                   'observation satellites ever built, and it is still in orbit.',
        'science': 'Ten instruments monitored land, oceans, ice and atmosphere '
                   'for a decade, including radar imaging of the surface.',
        'wiki': 'Envisat',
    },
    25994: {
        'mission': 'Terra (NASA Earth Observing System flagship)',
        'history': 'Launched in December 1999 from Vandenberg. The first of '
                   'NASA\'s large Earth Observing System satellites.',
        'science': 'Carries five instruments including MODIS, ASTER, MISR and '
                   'CERES, studying land, clouds, aerosols and the energy balance '
                   'of the planet.',
        'wiki': 'Terra_(satellite)',
    },
    27424: {
        'mission': 'Aqua (NASA Earth Observing System satellite)',
        'history': 'Launched in May 2002 from Vandenberg as part of the same '
                   'program as Terra.',
        'science': 'Studies the water cycle: evaporation, clouds, '
                   'precipitation, sea ice and atmospheric temperature. '
                   'Instruments include MODIS, AIRS and CERES.',
        'wiki': 'Aqua_(satellite)',
    },
    39084: {
        'mission': 'Landsat 8',
        'history': 'Launched in February 2013 from Vandenberg. Part of the '
                   'NASA and USGS Landsat program, which has imaged Earth '
                   'continuously since 1972.',
        'science': 'Multispectral and thermal imaging for land use, agriculture, '
                   'forests, water and wildfire mapping.',
        'wiki': 'Landsat_8',
    },
    49260: {
        'mission': 'Landsat 9',
        'history': 'Launched in September 2021 from Vandenberg. Continues the '
                   'NASA and USGS Landsat record alongside Landsat 8.',
        'science': 'Multispectral and thermal imaging, the same job as Landsat 8 '
                   'with updated sensors.',
        'wiki': 'Landsat_9',
    },
}