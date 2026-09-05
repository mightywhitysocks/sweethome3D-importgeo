package com.eteks.sweethome3d.io;

import java.io.*;
import java.net.*;
import java.util.zip.*;
import javax.xml.parsers.*;
import com.eteks.sweethome3d.model.*;

/**
 * Convertit un ZIP {Home.xml + modeles} (produit par build_home.py) en un vrai
 * fichier .sh3d (avec le Home serialise que le loader SH3D exige).
 *
 *   java -cp SweetHome3D.jar;<cls>  com.eteks.sweethome3d.io.Conv  <in.zip>  <out.sh3d>
 *
 * Doit tourner dans le package com.eteks.sweethome3d.io (setContentContext est
 * package-private) -> compiler en .class sur le classpath, PAS en mode source.
 *
 * `preferXmlEntry=true` (5e argument du HomeFileRecorder ci-dessous) : en plus
 * de l'entree `Home` serialisee Java (seule lue par le desktop), fait ecrire
 * une entree `Home.xml` (via HomeXMLExporter, chemins de contenu deja corrects
 * -- renumerotes par ContentDigests) dans le meme .sh3d. Necessaire pour
 * l'appli mobile / Sweet Home 3D Online : leur moteur JS (SweetHome3DJS,
 * transpile JSweet) ne sait PAS deserialiser l'entree Java `Home`, seulement
 * parser du XML -- confirme par test reel (`tools/mobile_compat_check/`,
 * chargement Chromium headless du meme moteur JS officiel) : sans cette
 * option, echec explicite "No Home.xml entry" ; avec elle, chargement propre.
 * Sans impact desktop (toujours l'entree `Home` qui est lue en priorite).
 */
public class Conv {
  public static void main(String[] a) throws Exception {
    File inZip = new File(a[0]).getCanonicalFile();
    String out = a[1];
    // HomeContentContext veut l'URL PLATE du zip (il ajoute lui-meme jar:...!/entree)
    URL zipUrl = inZip.toURI().toURL();

    HomeContentContext ctx = new HomeContentContext(zipUrl, null, true);
    HomeXMLHandler handler = new HomeXMLHandler();
    handler.setContentContext(ctx);

    SAXParserFactory f = SAXParserFactory.newInstance();
    f.setValidating(false);
    try {
      f.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
    } catch (Exception ignore) { }

    try (ZipFile zf = new ZipFile(inZip);
         InputStream in = zf.getInputStream(zf.getEntry("Home.xml"))) {
      f.newSAXParser().parse(new BufferedInputStream(in), handler);
    }
    Home home = handler.getHome();
    java.util.Map<String, Integer> byLevel = new java.util.TreeMap<>();
    countByLevel(home.getFurniture(), byLevel);
    System.out.println("parsed: " + home.getLevels().size() + " niveaux, "
        + byLevel.values().stream().mapToInt(Integer::intValue).sum() + " meubles "
        + byLevel + ", " + home.getRooms().size() + " pieces-plan");

    new HomeFileRecorder(9, false, null, false, true, false).writeHome(home, out);
    System.out.println("ecrit : " + out + "  (" + new File(out).length() + " o)");

    // controle : relire le .sh3d ecrit et verifier la repartition par niveau
    Home rr = new HomeFileRecorder(9, false).readHome(out);
    java.util.Map<String, Integer> chk = new java.util.TreeMap<>();
    countByLevel(rr.getFurniture(), chk);
    System.out.println("relu : " + rr.getLevels().size() + " niveaux, meubles " + chk);
  }

  private static void countByLevel(java.util.List<HomePieceOfFurniture> furniture,
                                    java.util.Map<String, Integer> byLevel) {
    countByLevel(furniture, byLevel, null);
  }

  /** Compte les meubles terminaux par niveau, en descendant dans les HomeFurnitureGroup :
   * seul le groupe porte un level (les enfants n'en ont pas), qu'on propage donc a eux. */
  private static void countByLevel(java.util.List<HomePieceOfFurniture> furniture,
                                    java.util.Map<String, Integer> byLevel,
                                    String inheritedLevel) {
    for (HomePieceOfFurniture p : furniture) {
      String levelName = p.getLevel() == null ? inheritedLevel : p.getLevel().getName();
      if (p instanceof HomeFurnitureGroup) {
        countByLevel(((HomeFurnitureGroup) p).getFurniture(), byLevel, levelName);
      } else {
        byLevel.merge(levelName == null ? "<null>" : levelName, 1, Integer::sum);
      }
    }
  }
}
