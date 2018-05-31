#
# LSST Data Management System
# Copyright 2017 LSST/AURA.
#
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the LSST License Statement and
# the GNU General Public License along with this program.  If not,
# see <http://www.lsstcorp.org/LegalNotices/>.
#

from collections import OrderedDict as oDict

import numpy as np

import lsst.afw.table as afwTable

__all__ = ["make_minimal_dia_object_schema",
           "make_minimal_dia_source_schema",
           "ccdVisitSchema"]


"""Defines afw schemas and conversions for use in ap_association tasks.

Until a more finalized interface between the prompt products database (PPD) can
be established, we put many utility functions for converting `lsst.afw.table` and
`lsst.afw.image` objects to a PPD. This includes both mapping schemas between
different catalogs and the DB.
"""


def make_minimal_dia_object_schema(filter_names=[]):
    """Define and create the minimal schema required for a DIAObject.

    Parameters
    ----------
    filter_names : `list` of `str`s
        Names of the filters expect and compute means for.

    Return
    ------
    schema : `lsst.afw.table.Schema`
        Minimal schema for DIAObjects.
    """
    schema = afwTable.SourceTable.makeMinimalSchema()
    # For the MVP/S we currently only care about the position though
    # in the future we will add summary computations for fluxes etc.
    # as well as their errors.

    # In the future we would like to store a covariance of the coordinate.
    # This functionality is not defined in currently in the stack, so we will
    # hold off until it is implemented. This is to be addressed in DM-7101.
    schema.addField("pixelId", type='L')
    schema.addField("nDiaSources", type='L')
    for filter_name in filter_names:
        schema.addField("psFluxMean_%s" % filter_name, type='D')
        schema.addField("psFluxMeanErr_%s" % filter_name, type='D')
        schema.addField("psFluxSigma_%s" % filter_name, type='D')
    return schema


def make_minimal_dia_source_schema():
    """ Define and create the minimal schema required for a DIASource.

    Return
    ------
    schema : `lsst.afw.table.Schema`
        Minimal schema for DIAObjects.
    """
    schema = afwTable.SourceTable.makeMinimalSchema()
    schema.addField("diaObjectId", type='L')
    schema.addField("ccdVisitId", type='L')
    schema.addField("psFlux", type='D')
    schema.addField("psFluxErr", type='D')
    schema.addField("filterName", type='String', size=10)
    schema.addField("filterId", type='L')
    return schema


def ccdVisitSchema():
    """Define the schema for the CcdVisit table.

    Return
    ------
    ccdVisitNames: `collections.OrderedDict`
       Names of columns in the ccdVisit table.
    """
    return oDict([("ccdVisitId", "INTEGER PRIMARY KEY"),
                  ("ccdNum", "INTEGER"),
                  ("filterName", "TEXT"),
                  ("filterId", "INTEGER"),
                  ("ra", "REAL"),
                  ("decl", "REAL"),
                  ("expTime", "REAL"),
                  ("expMidptMJD", "REAL"),
                  ("fluxZeroPoint", "REAL"),
                  ("fluxZeroPointErr", "REAL")])


def get_ccd_visit_info_from_exposure(exposure):
    """
    Extract info on the ccd and visit from the exposure.

    Paramters
    ---------
    exposure : `lsst.afw.image.Exposure`
        Exposure to store information from.

    Returns
    -------
    values : `dict` of ``values``
        List values representing info taken from the exposure.
    """
    visit_info = exposure.getInfo().getVisitInfo()
    sphPoint = exposure.getWcs().getSkyOrigin()
    flux0, flux0_err = exposure.getCalib().getFluxMag0()
    filter_obj = exposure.getFilter()
    # Values list is:
    # [CcdVisitId ``int``,
    #  ccdNum ``int``,
    #  filterName ``str``,
    #  RA WCS center ``degrees``,
    #  DEC WCS center ``degrees``,
    #  exposure time ``seconds``,
    #  dateTimeMJD ``seconds``,
    #  flux zero point ``counts``,
    #  flux zero point error ``counts``]
    values = {'ccdVisitId': visit_info.getExposureId(),
              'ccdNum': exposure.getDetector().getId(),
              'filterName': filter_obj.getName(),
              'filterId': filter_obj.getId(),
              'ra': sphPoint.getRa().asDegrees(),
              'decl': sphPoint.getDec().asDegrees(),
              'expTime': visit_info.getExposureTime(),
              'expMidptMJD': visit_info.getDate().nsecs() * 10 ** -9,
              'fluxZeroPoint': flux0,
              'fluxZeroPointErr': flux0_err}
    return values


def add_dia_source_aliases_to_catalog(source_catalog):
    """Create the needed aliases on fluxes and other columns if the input
    catalog does not already have them.

    Parameters
    ----------
    source_catalog : `lsst.afw.table.SourceCatalog`
        Input source catalog to add alias columns to.
    """
    if not source_catalog.getSchema().contains(make_minimal_dia_source_schema()):
        # Create aliases to appropriate flux fields if they exist.
        schema_names = source_catalog.getSchema().getNames()
        if 'base_PsfFlux_flux' in schema_names and \
           'base_PsfFlux_fluxSigma' in schema_names and \
           'psFlux' not in schema_names and \
           'psFluxErr' not in schema_names:
                alias_map = source_catalog.getSchema().getAliasMap()
                alias_map.set('psFlux', 'base_PsfFlux_flux')
                alias_map.set('psFluxErr', 'base_PsfFlux_fluxSigma')


def convert_dia_source_to_asssoc_schema_and_calibrate(dia_sources,
                                                      obj_ids=None,
                                                      exposure=None):
    """Create aliases in for the input source catalog schema and overwrite
    values if requested.

    Parameters
    ----------
    dia_sources : `lsst.afw.table.SourceCatalog`
        Input source catalog to alias and overwrite values of.
    obj_ids:  array-like of `int`
        DIAObject ids to associated with the input DIASources. Overwrites
        the current value in diaObjectId column.
    exposure : `lsst.afw.image.Exposure`
        Exposure to copy flux and filter information from.
    """

    output_dia_sources = afwTable.SourceCatog(
        make_minimal_dia_source_schema())
    output_dia_sources.reserve(len(dia_sources))
    add_dia_source_aliases_to_catalog(dia_sources)
    dia_source_schema = dia_sources.getSchema()

    if exposure is None:
        exp_dict = None
    else:
        exp_dict = get_ccd_visit_info_from_exposure(exposure)

    for src_idx, source_record in enumerate(dia_sources):
        if obj_ids is None:
            obj_id = None
        else:
            obj_id = obj_ids[src_idx]
        overwrite_dict = make_overwrite_dict(source_record, obj_id, exp_dict)
        output_record = output_dia_sources.addNew()
        copy_source_record(source_record,
                           output_record,
                           dia_source_schema,
                           overwrite_dict)
    return output_dia_sources


def make_overwrite_dict(source_record, obj_id=None, exp_dict=None):
    """Create a dictionary of values to overwrite the values stored in an
    afw.table or when storing values in a DB.

    Parameters
    ----------
    source_record : `lsst.afw.table.SourceRecord`
        Input source catalog to modify values of if needed.
    obj_id : `int` (optional)
        DIAObject id to overwrite.
    exp_dict : `dict`
        Dictionary of exposure properties for this source_catalog.

    Returns
    -------
    overwrite_dict : `dict`
        Dictionary of keys and values to overwrite for this source record.
    """
    overwrite_dict = {}
    if obj_id is not None:
        overwrite_dict['diaObjectId'] = int(obj_id)
    if exp_dict is not None:
        psFlux = source_record['psFlux']
        psFluxErr = source_record['psFluxErr']

        overwrite_dict['psFlux'] = psFlux / exp_dict['fluxZeroPoint']
        overwrite_dict['psFluxErr'] = np.sqrt(
            (psFluxErr / exp_dict['fluxZeroPoint']) ** 2 +
            (psFlux * exp_dict['fluxZeroPointErr'] /
             exp_dict['fluxZeroPoint'] ** 2) ** 2)
        overwrite_dict['ccdVisitId'] = exp_dict['ccdVisitId']
        overwrite_dict['filterName'] = exp_dict['filterName']
        overwrite_dict['filterId'] = exp_dict['filterId']

    return overwrite_dict


def copy_source_record(source_record,
                       output_record,
                       source_record_schema,
                       overwrite_dict):
    """Copy values from an input source record to a record with the proper
    schema for ap_association.

    Parameters
    ----------
    source_record : `lsst.afw.table.SourceRecord`
       Input source record to copy values from.
    output_record : `lsst.afw.table.SourceRecord`
        Output source record to copy values into and edit values of.
    source_record_schema : `lsst.afw.table.Schema`
        Schema of the input source record.
    overwrite_dict : `dict` of ``values``
        Dictionary with column names and values to overwrite into the
        output source record.
    """
    for sub_schema in make_minimal_dia_source_schema():
        field_name = sub_schema.getField().getName()
        if field_name in overwrite_dict:
            output_record.set(sub_schema.getKey(),
                              overwrite_dict[field_name])
        else:
            output_record.set(
                sub_schema.getKey(),
                source_record_schema.find(field_name).getKey())
